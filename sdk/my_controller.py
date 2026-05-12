"""
=============================================================================
  立体视觉汽车控制器 — 赛道颜色分割 + PID 版本
=============================================================================
  使用赛道区域颜色（暗色）阈值分割 + 矩重心找赛道中心，
  再通过 PID 计算转向，对直道和弯道均有良好鲁棒性。
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import cv2
import numpy as np


# ═══════════════════════════ 参数配置区 ══════════════════════════════════

# --- 摄像头 ---
LEFT_CAMERA_NAME: str = "left_camera"
RIGHT_CAMERA_NAME: str = "right_camera"
CAMERA_WIDTH: int = 640
CAMERA_HEIGHT: int = 480
CAMERA_FOV: float = 1.3

# --- ROI: 只看图像中部水平带，减少天空/车身干扰 ---
ROI_TOP: int = int(CAMERA_HEIGHT * 0.50)    # ROI 顶部行
ROI_BOT: int = int(CAMERA_HEIGHT * 0.95)    # ROI 底部行

# --- 赛道颜色阈值（深色赛道，背景较亮）---
# 低于此灰度值的像素被认为是赛道
TRACK_THRESHOLD: int = 80
# 检测有效所需的最小赛道像素数
MIN_TRACK_PIXELS: int = 200

# --- PID 参数 ---
KP: float = 1.4      # 比例系数
KI: float = 0.0      # 积分系数（直道容易飘，保持0）
KD: float = 0.4      # 微分系数（抑制振荡）

# --- 速度控制 ---
BASE_SPEED: float = 15.0      # 基础速度 (km/h)
MIN_SPEED: float = 5.0        # 最小速度 (km/h)
MAX_SPEED: float = 25.0       # 最大速度 (km/h)
SPEED_TURN_PENALTY: float = 0.8  # 转弯速度衰减系数

# --- 转向控制 ---
MAX_STEER_ANGLE: float = 0.85  # 最大转向角度（弧度）
STEER_CLAMP: float = 1.0       # 转向归一化上限
STEER_ALPHA: float = 0.55      # 转向低通滤波系数（越大越平滑）

# --- 转向灯 ---
SIGNAL_THRESHOLD: float = 0.25


# ═══════════════════════════ 图像处理函数 ═════════════════════════════════

def camera_to_bgr(camera) -> Optional[np.ndarray]:
    """将 Webots 摄像头图像转换为 OpenCV BGR 格式。"""
    width = camera.getWidth()
    height = camera.getHeight()
    image = camera.getImage()
    if image is None:
        return None
    buffer = np.frombuffer(image, np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(buffer, cv2.COLOR_BGRA2BGR)


def _track_center_x(bgr: np.ndarray) -> Optional[float]:
    """
    用暗色阈值分割 + 矩重心计算赛道中心 x 坐标。

    对直道和弯道都有效，不依赖直线检测。
    返回：赛道中心像素坐标，检测失败返回 None。
    """
    roi = bgr[ROI_TOP:ROI_BOT]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, th = cv2.threshold(blur, TRACK_THRESHOLD, 255, cv2.THRESH_BINARY_INV)
    # 形态学开运算除噪点
    kernel = np.ones((5, 5), np.uint8)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel)
    m = cv2.moments(th)
    if m["m00"] < MIN_TRACK_PIXELS:
        return None
    return float(m["m10"] / m["m00"])


def _estimate_center_error(
    left_bgr: Optional[np.ndarray],
    right_bgr: Optional[np.ndarray],
) -> Optional[float]:
    """
    融合左右摄像头检测赛道中心，返回归一化偏差 error。

    error > 0: 赛道中心在画面右侧，需右转
    error < 0: 赛道中心在画面左侧，需左转
    """
    cx_l = _track_center_x(left_bgr) if left_bgr is not None else None
    cx_r = _track_center_x(right_bgr) if right_bgr is not None else None

    if cx_l is not None and cx_r is not None:
        cx = (cx_l + cx_r) / 2.0
    elif cx_r is not None:
        cx = cx_r          # 优先用向前的右摄像头
    elif cx_l is not None:
        cx = cx_l
    else:
        return None

    return float((cx - CAMERA_WIDTH / 2.0) / (CAMERA_WIDTH / 2.0))


def clamp(value: float, min_v: float, max_v: float) -> float:
    """将值限制在 [min_v, max_v] 范围内。"""
    return float(max(min_v, min(max_v, value)))


# 兼容旧接口的占位函数（不再被主要逻辑使用）
def frame_has_lane_features(frame: Optional[np.ndarray]) -> bool:
    return frame is not None


def combine_offsets(lo: float, lc: float, ro: float, rc: float) -> float:
    total = lc + rc
    return float((lo * lc + ro * rc) / total) if total > 0 else 0.0


# ═══════════════════════════ PID 全局状态 ════════════════════════════════

_pid_prev_error: float = 0.0
_pid_integral: float = 0.0
_pid_steer_lpf: float = 0.0


# ═══════════════════════════ 控制逻辑 ════════════════════════════════════

def decide_speed(steering: float, confidence: float) -> float:
    """根据转向幅度决定速度，转弯越急速度越低。"""
    speed = BASE_SPEED * (1.0 - SPEED_TURN_PENALTY * abs(steering))
    return clamp(speed, MIN_SPEED, MAX_SPEED)


def decide_turn_signal(steering: float) -> str:
    if steering < -SIGNAL_THRESHOLD:
        return "left"
    if steering > SIGNAL_THRESHOLD:
        return "right"
    return "off"


def compute_control(
    left_frame: Optional[np.ndarray],
    right_frame: Optional[np.ndarray],
    prev_left_gray: Optional[np.ndarray],
    prev_right_gray: Optional[np.ndarray],
    filtered_offset: float,
    filtered_conf: float,
    last_steering: float,
) -> Tuple[float, float, str, Optional[np.ndarray], Optional[np.ndarray], float, float, float]:
    """
    核心控制函数（PID + 赛道颜色分割）。
    保持返回值签名不变以兼容 run() 和 control()。
    """
    global _pid_prev_error, _pid_integral, _pid_steer_lpf

    # 检测赛道中心偏差
    error = _estimate_center_error(left_frame, right_frame)

    if error is None:
        # 检测失败：保持上一帧转向缓慢衰减
        steering = last_steering * 0.85
        speed = decide_speed(steering, 0.0)
        signal = decide_turn_signal(steering)
        new_lg = prev_left_gray
        new_rg = prev_right_gray
        return (steering, speed, signal, new_lg, new_rg,
                filtered_offset, filtered_conf, steering)

    # PID 计算（固定 dt=0.032s，约 30Hz）
    dt = 0.032
    derivative = float(np.clip((error - _pid_prev_error) / dt, -8.0, 8.0))
    _pid_integral = float(np.clip(_pid_integral + error * dt, -1.0, 1.0))

    steering_raw = KP * error + KI * _pid_integral + KD * derivative
    steering_raw = float(np.clip(steering_raw, -STEER_CLAMP, STEER_CLAMP))

    # 低通滤波
    _pid_steer_lpf = STEER_ALPHA * steering_raw + (1.0 - STEER_ALPHA) * _pid_steer_lpf
    steering = float(np.clip(_pid_steer_lpf, -STEER_CLAMP, STEER_CLAMP))

    speed = decide_speed(steering, 1.0)
    signal = decide_turn_signal(steering)

    _pid_prev_error = error

    new_lg = cv2.cvtColor(left_frame, cv2.COLOR_BGR2GRAY) if left_frame is not None else prev_left_gray
    new_rg = cv2.cvtColor(right_frame, cv2.COLOR_BGR2GRAY) if right_frame is not None else prev_right_gray

    return (steering, speed, signal, new_lg, new_rg,
            filtered_offset, filtered_conf, steering)


# ═══════════════════════════ Webots 设备初始化和主循环 ═══════════════════

def get_device(robot, names):
    for name in names:
        try:
            dev = robot.getDevice(name)
        except Exception:
            dev = None
        if dev is not None:
            return dev
    return None


def set_indicator_with_driver(driver, signal: str) -> bool:
    set_indicator = getattr(driver, "setIndicator", None)
    if set_indicator is None:
        return False
    left_const = getattr(driver, "INDICATOR_LEFT", None)
    right_const = getattr(driver, "INDICATOR_RIGHT", None)
    off_const = getattr(driver, "INDICATOR_OFF", None)
    if left_const is None or right_const is None or off_const is None:
        return False
    try:
        if signal == "left":
            set_indicator(left_const)
        elif signal == "right":
            set_indicator(right_const)
        else:
            set_indicator(off_const)
    except (AttributeError, RuntimeError):
        return False
    return True


def init_indicator_leds(robot):
    left_led = get_device(robot, ["left_indicator", "left_signal", "left_blinker", "indicator_left"])
    right_led = get_device(robot, ["right_indicator", "right_signal", "right_blinker", "indicator_right"])
    return left_led, right_led


def set_indicator_with_leds(left_led, right_led, signal: str) -> None:
    if left_led is None and right_led is None:
        return
    left_val = 1.0 if signal == "left" else 0.0
    right_val = 1.0 if signal == "right" else 0.0
    if left_led is not None:
        left_led.set(left_val)
    if right_led is not None:
        right_led.set(right_val)


def run() -> None:
    """主函数：初始化 Webots 设备并进入控制循环。"""
    try:
        from vehicle import Driver  # type: ignore
        driver = Driver()
        robot = driver
        use_driver = True
        print("[Controller] 使用 Driver API")
    except Exception:
        from controller import Robot  # type: ignore
        driver = Robot()
        robot = driver
        use_driver = False
        print("[Controller] 使用 Robot API")

    timestep = int(robot.getBasicTimeStep())

    left_camera = get_device(robot, [LEFT_CAMERA_NAME])
    right_camera = get_device(robot, [RIGHT_CAMERA_NAME])

    if left_camera is None and right_camera is None:
        raise RuntimeError("未找到摄像头！请确保 PROTO 文件中配置了 left_camera 和 right_camera。")

    if left_camera is not None:
        left_camera.enable(timestep)
        print(f"[Controller] 左摄像头已启用: {LEFT_CAMERA_NAME}")
    if right_camera is not None:
        right_camera.enable(timestep)
        print(f"[Controller] 右摄像头已启用: {RIGHT_CAMERA_NAME}")

    gps = get_device(robot, ["gps", "GPS"])
    if gps is not None:
        gps.enable(timestep)

    compass = get_device(robot, ["compass", "Compass"])
    if compass is not None:
        compass.enable(timestep)

    left_motor = right_motor = None
    fl_steer = fr_steer = None

    if not use_driver:
        try:
            left_motor = robot.getDevice("left_motor")
            right_motor = robot.getDevice("right_motor")
            fl_steer = robot.getDevice("fl_steer")
            fr_steer = robot.getDevice("fr_steer")
            for motor in (left_motor, right_motor):
                if motor is not None:
                    motor.setPosition(float("inf"))
                    motor.setVelocity(0.0)
        except Exception:
            left_motor = right_motor = None
        fl_steer = fr_steer = None

    left_indicator_led, right_indicator_led = (None, None)
    if not use_driver:
        left_indicator_led, right_indicator_led = init_indicator_leds(robot)

    prev_left_gray: Optional[np.ndarray] = None
    prev_right_gray: Optional[np.ndarray] = None
    filtered_offset: float = 0.0
    filtered_conf: float = 0.0
    last_steering: float = 0.0

    print("[Controller] 初始化完成，进入控制循环...")

    while (driver.step() if use_driver else robot.step(timestep)) != -1:
        left_frame = camera_to_bgr(left_camera) if left_camera is not None else None
        right_frame = camera_to_bgr(right_camera) if right_camera is not None else None

        if left_frame is None and right_frame is None:
            continue

        (
            steering, speed, signal,
            prev_left_gray, prev_right_gray,
            filtered_offset, filtered_conf, last_steering,
        ) = compute_control(
            left_frame, right_frame,
            prev_left_gray, prev_right_gray,
            filtered_offset, filtered_conf, last_steering,
        )

        steer_angle = clamp(steering * MAX_STEER_ANGLE, -MAX_STEER_ANGLE, MAX_STEER_ANGLE)

        if use_driver:
            driver.setCruisingSpeed(speed)
            driver.setSteeringAngle(steer_angle)
            if not set_indicator_with_driver(driver, signal):
                set_indicator_with_leds(left_indicator_led, right_indicator_led, signal)
        else:
            if fl_steer is not None:
                fl_steer.setPosition(steer_angle)
            if fr_steer is not None:
                fr_steer.setPosition(steer_angle)
            if left_motor is not None and right_motor is not None:
                wheel_speed = clamp(speed / MAX_SPEED, 0.0, 1.0)
                base = 8000.0 * wheel_speed
                diff = steering * 4000.0
                left_motor.setVelocity(base + diff)
                right_motor.setVelocity(base - diff)
            set_indicator_with_leds(left_indicator_led, right_indicator_led, signal)

    print("[Controller] 控制循环结束")


# ═══════════════════════════ SDK 沙箱入口 ════════════════════════════════

_state: dict = {
    "filtered_offset": 0.0,
    "filtered_conf": 0.0,
    "last_steering": 0.0,
    "prev_left_gray": None,
    "prev_right_gray": None,
}


def control(
    left_img: np.ndarray,
    right_img: np.ndarray,
    timestamp: float,
) -> tuple:
    """
    SDK 沙箱入口函数（必须定义，不可改签名）。

    参数:
        left_img:  左摄像头图像 (480, 640, 3), uint8, BGR
        right_img: 右摄像头图像 (480, 640, 3), uint8, BGR
        timestamp: 当前时间戳（秒）

    返回:
        (steering, speed)
            steering in [-1, 1]  负值左转，正值右转
            speed    in [0, 1]   归一化速度
    """
    s = _state

    left_frame = left_img if (left_img is not None and left_img.size > 0) else None
    right_frame = right_img if (right_img is not None and right_img.size > 0) else None

    (
        steering, speed, _signal,
        s["prev_left_gray"], s["prev_right_gray"],
        s["filtered_offset"], s["filtered_conf"], s["last_steering"],
    ) = compute_control(
        left_frame, right_frame,
        s["prev_left_gray"], s["prev_right_gray"],
        s["filtered_offset"], s["filtered_conf"], s["last_steering"],
    )

    speed_normalized = clamp(speed / MAX_SPEED, 0.0, 1.0)
    return float(steering), float(speed_normalized)


if __name__ == "__main__":
    run()
"""
=============================================================================
  单目左摄像头控制器 — 白线引导 + 栏杆避障版本
=============================================================================
  策略：
    1. 白线检测（地面白色标线）→ PID 跟踪白线中心，确定基础转向方向
    2. 栏杆检测（图像中竖向深色竖条/护栏）→ 若栏杆过近则强制规避转向
    3. 仅使用左摄像头（left_camera），右摄像头图像被忽略

  图像坐标系：
    - 白线检测 ROI：图像下半部分（靠近车头的地面）
    - 栏杆检测 ROI：图像上半/中部（远处栏杆/护栏）

  接口（必须保留）：
    control(left_img, right_img, timestamp) -> (steering, speed)
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import cv2
import numpy as np


# ══════════════════════════════ 参数配置 ══════════════════════════════════

# --- 图像尺寸 ---
IMG_H: int = 480
IMG_W: int = 640

# ── 白线检测 ROI（图像底部，近处地面）──
WHITE_ROI_TOP: int = int(IMG_H * 0.60)
WHITE_ROI_BOT: int = int(IMG_H * 0.95)

# 白色像素阈值（HSV中高Value/低Saturation）
WHITE_V_MIN: int = 180
WHITE_S_MAX: int = 60
WHITE_MIN_PIXELS: int = 150

# ── 栏杆检测 ROI（图像中上部，远处障碍）──
RAIL_ROI_TOP: int = int(IMG_H * 0.25)
RAIL_ROI_BOT: int = int(IMG_H * 0.65)

# 栏杆危险阈值
RAIL_DANGER_WIDTH: int = 60
RAIL_DARK_THRESHOLD: int = 55
RAIL_MIN_HEIGHT: int = 30

# ── PID 参数（跟踪白线） ──
KP: float = 1.3
KI: float = 0.0
KD: float = 0.35

# ── 速度参数 ──
BASE_SPEED: float = 0.45
MIN_SPEED: float = 0.15
MAX_SPEED: float = 0.65
SPEED_TURN_PENALTY: float = 0.7

# ── 转向限制 ──
MAX_STEER: float = 1.0
STEER_ALPHA: float = 0.50

# ── 栏杆规避转向强度 ──
RAIL_AVOID_STEER: float = 0.65

# ── 最大转向角（Webots Driver）──
MAX_STEER_ANGLE: float = 0.85


# ══════════════════════════════ 状态变量 ══════════════════════════════════

_pid_prev_error: float = 0.0
_pid_integral: float = 0.0
_steer_lpf: float = 0.0
_last_steering: float = 0.0
_no_white_count: int = 0


# ══════════════════════════════ 工具函数 ══════════════════════════════════

def _clamp(v: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, v)))


# ══════════════════════════════ 白线检测 ══════════════════════════════════

def detect_white_line_cx(bgr: np.ndarray) -> Optional[float]:
    """
    在底部 ROI 中检测白色地面线，返回其重心 x 坐标（像素）。
    检测失败返回 None。
    """
    roi = bgr[WHITE_ROI_TOP:WHITE_ROI_BOT]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # 提取白色：高亮度 + 低饱和
    mask = cv2.inRange(
        hsv,
        np.array([0, 0, WHITE_V_MIN], dtype=np.uint8),
        np.array([180, WHITE_S_MAX, 255], dtype=np.uint8),
    )

    # 形态学去噪
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)

    m = cv2.moments(mask)
    if m["m00"] < WHITE_MIN_PIXELS:
        return None
    return float(m["m10"] / m["m00"])


# ══════════════════════════════ 栏杆检测 ══════════════════════════════════

def detect_rail_threat(bgr: np.ndarray) -> Optional[str]:
    """
    在中上部 ROI 中检测栏杆（竖向深色条纹）。

    返回：
      "left"  - 左侧存在危险栏杆，需右转规避
      "right" - 右侧存在危险栏杆，需左转规避
      None    - 无明显危险栏杆
    """
    roi = bgr[RAIL_ROI_TOP:RAIL_ROI_BOT]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    # 深色像素掩码
    dark_mask = (blur < RAIL_DARK_THRESHOLD).astype(np.uint8) * 255

    # 保留竖向结构
    v_kernel = np.ones((RAIL_MIN_HEIGHT, 1), np.uint8)
    rail_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, v_kernel)

    # 分析左右半区竖向暗像素密度
    mid = IMG_W // 2
    left_half = rail_mask[:, :mid]
    right_half = rail_mask[:, mid:]

    left_col_density = int((left_half > 0).any(axis=0).sum())
    right_col_density = int((right_half > 0).any(axis=0).sum())

    if left_col_density > RAIL_DANGER_WIDTH and left_col_density > right_col_density * 1.4:
        return "left"
    if right_col_density > RAIL_DANGER_WIDTH and right_col_density > left_col_density * 1.4:
        return "right"
    return None


# ══════════════════════════════ 核心控制 ══════════════════════════════════

def compute_steering(left_bgr: np.ndarray) -> float:
    """综合白线追踪 + 栏杆避障，返回转向值 [-1, 1]。"""
    global _pid_prev_error, _pid_integral, _steer_lpf, _last_steering, _no_white_count

    # ── 1. 白线检测 ──
    cx = detect_white_line_cx(left_bgr)

    if cx is not None:
        _no_white_count = 0
        error = float((cx - IMG_W / 2.0) / (IMG_W / 2.0))
    else:
        _no_white_count += 1
        error = _pid_prev_error * 0.80

    # ── 2. PID 计算 ──
    dt = 0.032
    d_error = _clamp((error - _pid_prev_error) / dt, -8.0, 8.0)
    _pid_integral = _clamp(_pid_integral + error * dt, -1.0, 1.0)

    steer_raw = KP * error + KI * _pid_integral + KD * d_error
    steer_raw = _clamp(steer_raw, -MAX_STEER, MAX_STEER)

    _pid_prev_error = error

    # ── 3. 栏杆避障覆写（优先级高于白线） ──
    rail_threat = detect_rail_threat(left_bgr)
    if rail_threat == "left":
        steer_raw = max(steer_raw, RAIL_AVOID_STEER)
    elif rail_threat == "right":
        steer_raw = min(steer_raw, -RAIL_AVOID_STEER)

    # ── 4. 低通滤波平滑 ──
    _steer_lpf = STEER_ALPHA * steer_raw + (1.0 - STEER_ALPHA) * _steer_lpf
    steering = _clamp(_steer_lpf, -MAX_STEER, MAX_STEER)

    _last_steering = steering
    return steering


def compute_speed(steering: float) -> float:
    """根据转向幅度决定速度。"""
    speed = BASE_SPEED * (1.0 - SPEED_TURN_PENALTY * abs(steering))
    return _clamp(speed, MIN_SPEED, MAX_SPEED)


# ══════════════════════════════ SDK 入口 ══════════════════════════════════

def control(
    left_img: np.ndarray,
    right_img: np.ndarray,
    timestamp: float,
) -> tuple[float, float]:
    """
    SDK 沙箱必须入口函数（签名不可更改）。

    参数:
        left_img:  左摄像头图像 (480, 640, 3) uint8 BGR  ← 本控制器使用
        right_img: 右摄像头图像 (480, 640, 3) uint8 BGR  ← 本控制器忽略
        timestamp: 当前时间戳（秒）

    返回:
        (steering, speed)
            steering ∈ [-1.0, 1.0]   负值=左转，正值=右转
            speed    ∈ [0.0, 1.0]    归一化速度
    """
    if left_img is None or left_img.size == 0 or left_img.shape != (IMG_H, IMG_W, 3):
        return 0.0, 0.0

    try:
        steering = compute_steering(left_img)
        speed = compute_speed(steering)
    except Exception:
        steering, speed = 0.0, 0.1

    return float(steering), float(speed)


# ══════════════════════════════ Webots 主循环 ══════════════════════════════

def _get_device(robot, names):
    for name in names:
        try:
            dev = robot.getDevice(name)
        except Exception:
            dev = None
        if dev is not None:
            return dev
    return None


def run() -> None:
    """Webots 原生运行入口。"""
    try:
        from vehicle import Driver  # type: ignore
        driver = Driver()
        robot = driver
        use_driver = True
        print("[Controller] 使用 Driver API")
    except Exception:
        from controller import Robot  # type: ignore
        robot = Robot()
        driver = robot
        use_driver = False
        print("[Controller] 使用 Robot API")

    timestep = int(robot.getBasicTimeStep())

    left_camera = _get_device(robot, ["left_camera"])
    if left_camera is None:
        raise RuntimeError("未找到 left_camera，请确认 PROTO 配置正确。")

    left_camera.enable(timestep)
    print("[Controller] 左摄像头已启用: left_camera")

    gps = _get_device(robot, ["gps", "GPS"])
    if gps is not None:
        gps.enable(timestep)

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
            left_motor = right_motor = fl_steer = fr_steer = None

    print("[Controller] 初始化完成，进入控制循环（仅左摄像头）...")

    while (driver.step() if use_driver else robot.step(timestep)) != -1:
        raw = left_camera.getImage()
        if raw is None:
            continue

        w = left_camera.getWidth()
        h = left_camera.getHeight()
        buf = np.frombuffer(raw, np.uint8).reshape((h, w, 4))
        left_bgr = cv2.cvtColor(buf, cv2.COLOR_BGRA2BGR)

        steering = compute_steering(left_bgr)
        speed = compute_speed(steering)
        steer_angle = _clamp(steering * MAX_STEER_ANGLE, -MAX_STEER_ANGLE, MAX_STEER_ANGLE)

        if use_driver:
            driver.setCruisingSpeed(speed * 25.0)
            driver.setSteeringAngle(steer_angle)
        else:
            if fl_steer is not None:
                fl_steer.setPosition(steer_angle)
            if fr_steer is not None:
                fr_steer.setPosition(steer_angle)
            if left_motor is not None and right_motor is not None:
                wheel_v = speed * 8000.0
                diff = steering * 4000.0
                left_motor.setVelocity(wheel_v + diff)
                right_motor.setVelocity(wheel_v - diff)

    print("[Controller] 控制循环结束")


if __name__ == "__main__":
    run()

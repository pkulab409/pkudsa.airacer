#!/usr/bin/env python3
"""
=============================================================================
  立体视觉汽车控制器范例 (Stereo Vision Car Controller Example)
  =============================================================================

  本文件是一个完整的 Webots 汽车控制器，演示如何通过左右两个摄像头
  获取图像信息，使用 OpenCV 进行视觉分析，并控制汽车的速度和转向。

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  使用说明：                                                             │
  │  1. 将此文件复制到你的团队控制器目录                                     │
  │  2. 修改下方 "========== 可修改配置区 ==========" 中的参数               │
  │  3. 在 "========== 可修改控制逻辑区 ==========" 中实现你的控制算法       │
  │  4. 其余代码（图像处理、设备初始化等）一般不需要修改                     │
  └─────────────────────────────────────────────────────────────────────────┘

  摄像头配置（来自 PROTO 文件）：
    - left_camera:  位置 (1.1, 0, 0.1)，旋转 0.4 rad（向左偏）
    - right_camera: 位置 (1.1, 0, 0.1)，旋转 0 rad（向前）
    - 分辨率: 640 x 480，视野角: 1.3 rad

  依赖：
    - Webots Python API (controller 模块)
    - OpenCV (cv2)
    - NumPy (numpy)
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import cv2
import numpy as np


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  可修改配置区 — 你可以根据需求调整这些参数                               ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#   TODO: 以下参数你可以自由修改，以适应不同的赛道和驾驶风格

# --- 摄像头参数（一般不需要修改，除非你改了 PROTO 文件中的摄像头配置） ---
LEFT_CAMERA_NAME: str = "left_camera"      # 左摄像头名称
RIGHT_CAMERA_NAME: str = "right_camera"    # 右摄像头名称
CAMERA_WIDTH: int = 640                    # 图像宽度（像素）
CAMERA_HEIGHT: int = 480                   # 图像高度（像素）
CAMERA_FOV: float = 1.3                    # 视野角（弧度）

# --- 速度控制参数 ---
# TODO: 根据你的赛车调校这些速度值
BASE_SPEED: float = 15.0                   # 基础速度 (km/h)
MIN_SPEED: float = 5.0                     # 最小速度 (km/h)
MAX_SPEED: float = 25.0                    # 最大速度 (km/h)
SPEED_TURN_PENALTY: float = 0.6            # 转弯时的速度衰减系数（0~1，越大转弯越慢）

# --- 转向控制参数 ---
# TODO: 根据你的赛车调校转向增益
STEER_GAIN: float = 2.5                    # 转向增益（越大转向越灵敏）
MAX_STEER_ANGLE: float = 0.85              # 最大转向角度（弧度）
STRAIGHT_DEADBAND: float = 0.02            # 直线死区（小于此值认为在直线上）

# --- 图像处理参数 ---
# TODO: 如果赛道颜色/光照不同，可能需要调整这些阈值
CANNY_LOW: int = 60                        # Canny 边缘检测低阈值
CANNY_HIGH: int = 160                      # Canny 边缘检测高阈值
GAUSSIAN_KERNEL: int = 5                   # 高斯模糊核大小（奇数）
HOUGH_VOTE: int = 50                       # Hough 变换投票阈值
HOUGH_MIN_LENGTH: int = 40                 # Hough 最小线段长度
HOUGH_MAX_GAP: int = 120                   # Hough 最大线段间隙

# --- ROI（感兴趣区域）参数 ---
# TODO: 如果摄像头安装位置不同，可能需要调整 ROI
ROI_BOTTOM_RATIO: float = 1.0              # ROI 底部占图像比例
ROI_TOP_RATIO: float = 0.65                # ROI 顶部占图像比例
ROI_LEFT_RATIO: float = 0.40               # ROI 左侧占图像比例
ROI_RIGHT_RATIO: float = 0.60              # ROI 右侧占图像比例

# --- 置信度与平滑参数 ---
# TODO: 如果图像噪声大，可以增大平滑系数
OFFSET_SMOOTHING: float = 0.7              # 偏移量平滑系数（0~1，越大越平滑）
STEER_SMOOTHING: float = 0.6               # 转向平滑系数（0~1，越大越平滑）
MIN_CONFIDENCE: float = 0.15               # 最小置信度（低于此值认为检测不可靠）
FULL_CONFIDENCE_LINE_COUNT: float = 8.0    # 满置信度所需的线段数量
MIN_EDGE_DENSITY: float = 0.003            # 最小边缘密度（低于此值认为无车道特征）

# --- 转向信号阈值 ---
SIGNAL_THRESHOLD: float = 0.25             # 转向灯触发阈值


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  以下代码一般不需要修改 — 图像处理核心算法                               ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def camera_to_bgr(camera) -> Optional[np.ndarray]:
    """
    将 Webots 摄像头图像转换为 OpenCV BGR 格式。

    参数:
        camera: Webots Camera 设备对象

    返回:
        BGR 格式的 numpy 数组 (H x W x 3)，如果图像为空则返回 None

    注意:
        此函数不需要修改。Webots 返回 RGBA 格式，需要转换为 BGR。
    """
    width = camera.getWidth()
    height = camera.getHeight()
    image = camera.getImage()
    if image is None:
        return None
    buffer = np.frombuffer(image, np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(buffer, cv2.COLOR_BGRA2BGR)


def preprocess_edges(frame: np.ndarray) -> np.ndarray:
    """
    对输入帧进行边缘检测预处理。

    步骤:
        1. 转换为灰度图
        2. 高斯模糊降噪
        3. Canny 边缘检测

    参数:
        frame: BGR 图像 (H x W x 3)

    返回:
        二值边缘图像 (H x W)

    注意:
        此函数一般不需要修改。如果赛道环境特殊（如夜间、雨天），
        可以调整 CANNY_LOW/CANNY_HIGH 和 GAUSSIAN_KERNEL 参数。
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (GAUSSIAN_KERNEL, GAUSSIAN_KERNEL), 0)
    edges = cv2.Canny(blur, CANNY_LOW, CANNY_HIGH)
    return edges


def region_of_interest(edges: np.ndarray) -> np.ndarray:
    """
    提取感兴趣区域（ROI），只保留车道区域。

    创建一个梯形掩码，只保留图像下半部分的中间区域，
    因为车道线通常出现在这个区域。

    参数:
        edges: 二值边缘图像 (H x W)

    返回:
        只包含 ROI 区域的边缘图像

    注意:
        如果摄像头安装位置或角度改变，需要调整 ROI 参数。
        梯形顶点由 ROI_BOTTOM_RATIO, ROI_TOP_RATIO,
        ROI_LEFT_RATIO, ROI_RIGHT_RATIO 控制。
    """
    height, width = edges.shape
    mask = np.zeros_like(edges)
    polygon = np.array(
        [
            [0, int(height * ROI_BOTTOM_RATIO)],                          # 左下
            [width, int(height * ROI_BOTTOM_RATIO)],                      # 右下
            [int(width * ROI_RIGHT_RATIO), int(height * ROI_TOP_RATIO)],  # 右上
            [int(width * ROI_LEFT_RATIO), int(height * ROI_TOP_RATIO)],   # 左上
        ],
        np.int32,
    )
    cv2.fillPoly(mask, [polygon], 255)
    return cv2.bitwise_and(edges, mask)


def average_lane_lines(
    lines: Optional[np.ndarray],
) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """
    将 Hough 变换检测到的线段分类为左车道线和右车道线，并求平均。

    分类依据：
        - 斜率为负 -> 左车道线
        - 斜率为正 -> 右车道线
        - 排除水平线（|斜率| < 0.6）

    参数:
        lines: HoughLinesP 返回的线段数组

    返回:
        (left_line, right_line)，每条线表示为 (斜率, 截距)
        如果某侧没有检测到线段，则对应值为 None

    注意:
        此函数一般不需要修改。如果赛道有特殊形状（如 S 弯），
        可能需要调整斜率阈值。
    """
    if lines is None:
        return None, None
    left_lines = []
    right_lines = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if x2 == x1:
            continue
        slope = (y2 - y1) / (x2 - x1)
        if abs(slope) < 0.6:  # 排除水平线
            continue
        intercept = y1 - slope * x1
        if slope < 0:
            left_lines.append((slope, intercept))
        else:
            right_lines.append((slope, intercept))
    left = np.mean(left_lines, axis=0) if left_lines else None
    right = np.mean(right_lines, axis=0) if right_lines else None
    return left, right


def lane_center_offset(frame: Optional[np.ndarray]) -> Tuple[float, float]:
    """
    计算车辆相对于车道中心的偏移量。

    通过检测车道线，计算左右车道线的底部中点，
    与图像中心比较得到归一化偏移量。

    参数:
        frame: BGR 图像 (H x W x 3)

    返回:
        (offset, confidence):
            offset: 归一化偏移量 (-1~1)，负值偏左，正值偏右
            confidence: 检测置信度 (0~1)

    注意:
        此函数是核心视觉算法，一般不需要修改。
        如果检测效果不佳，可以调整 Hough 变换参数或 ROI 区域。
    """
    if frame is None:
        return 0.0, 0.0
    height, width = frame.shape[:2]
    edges = preprocess_edges(frame)
    roi = region_of_interest(edges)
    lines = cv2.HoughLinesP(
        roi,
        2,
        np.pi / 180,
        HOUGH_VOTE,
        minLineLength=HOUGH_MIN_LENGTH,
        maxLineGap=HOUGH_MAX_GAP,
    )
    line_count = 0 if lines is None else len(lines)
    left, right = average_lane_lines(lines)
    if left is None or right is None:
        return 0.0, 0.0

    y_bottom = height
    y_top = int(height * ROI_TOP_RATIO)

    def line_x(slope: float, intercept: float, y: int) -> int:
        return int((y - intercept) / slope)

    left_x_bottom = line_x(left[0], left[1], y_bottom)
    right_x_bottom = line_x(right[0], right[1], y_bottom)
    lane_center = (left_x_bottom + right_x_bottom) / 2.0
    image_center = width / 2.0
    offset = (lane_center - image_center) / image_center
    confidence = min(1.0, line_count / FULL_CONFIDENCE_LINE_COUNT)
    return float(offset), float(confidence)


def frame_has_lane_features(frame: Optional[np.ndarray]) -> bool:
    """
    检查图像中是否包含车道特征（边缘密度是否足够）。

    参数:
        frame: BGR 图像 (H x W x 3)

    返回:
        True 如果图像包含足够的车道特征

    注意:
        此函数用于过滤无效帧，一般不需要修改。
    """
    if frame is None:
        return False
    edges = preprocess_edges(frame)
    roi = region_of_interest(edges)
    edge_density = float(np.count_nonzero(roi)) / float(roi.size)
    return edge_density >= MIN_EDGE_DENSITY


def combine_offsets(
    left_offset: float, left_conf: float,
    right_offset: float, right_conf: float,
) -> float:
    """
    融合左右两个摄像头的偏移量，使用置信度加权平均。

    参数:
        left_offset: 左摄像头检测到的偏移量
        left_conf: 左摄像头的置信度
        right_offset: 右摄像头检测到的偏移量
        right_conf: 右摄像头的置信度

    返回:
        融合后的偏移量

    注意:
        此函数一般不需要修改。如果想让某个摄像头权重更大，
        可以修改加权方式。
    """
    total = left_conf + right_conf
    if total <= 0.0:
        return 0.0
    return float((left_offset * left_conf + right_offset * right_conf) / total)


def clamp(value: float, min_v: float, max_v: float) -> float:
    """将值限制在 [min_v, max_v] 范围内。"""
    return float(max(min_v, min(max_v, value)))


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  可修改控制逻辑区 — 你可以在这里实现自己的控制算法                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#   TODO: 以下函数是控制逻辑的核心，你可以完全重写它们来实现自己的策略

def decide_speed(steering: float, confidence: float) -> float:
    """
    根据转向角度和检测置信度决定速度。

    策略：
        - 转向越大，速度越慢（转弯减速）
        - 置信度越高，速度可以越快
        - 速度限制在 [MIN_SPEED, MAX_SPEED] 范围内

    参数:
        steering: 归一化转向角度 (-1~1)
        confidence: 车道检测置信度 (0~1)

    返回:
        目标速度 (km/h)

    TODO: 你可以修改此函数实现不同的速度策略，例如：
        - 直线加速、弯道减速
        - 根据赛道曲率调整速度
        - 根据前方障碍物调整速度
    """
    base = BASE_SPEED * (1.0 - SPEED_TURN_PENALTY * abs(steering))
    boosted = base + (MAX_SPEED - base) * 0.35 * confidence
    return clamp(boosted, MIN_SPEED, MAX_SPEED)


def decide_turn_signal(steering: float) -> str:
    """
    根据转向角度决定转向灯信号。

    参数:
        steering: 归一化转向角度 (-1~1)

    返回:
        "left", "right", 或 "off"

    TODO: 你可以修改此函数实现不同的转向灯策略。
    """
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
    核心控制函数：根据左右摄像头图像计算转向、速度和转向灯信号。

    这是整个控制器的核心函数。它：
    1. 分别对左右图像进行车道检测
    2. 融合两个摄像头的检测结果
    3. 计算转向角度
    4. 计算速度
    5. 决定转向灯信号

    参数:
        left_frame: 左摄像头 BGR 图像
        right_frame: 右摄像头 BGR 图像
        prev_left_gray: 上一帧左摄像头灰度图（用于变化检测）
        prev_right_gray: 上一帧右摄像头灰度图（用于变化检测）
        filtered_offset: 上一帧滤波后的偏移量
        filtered_conf: 上一帧滤波后的置信度
        last_steering: 上一帧的转向值

    返回:
        (steering, speed, signal, new_left_gray, new_right_gray,
         new_filtered_offset, new_filtered_conf, new_last_steering)

    TODO: 这是最重要的函数！你可以完全重写它来实现：
        - PID 控制
        - 强化学习策略
        - 基于深度学习的端到端控制
        - 其他任何你想到的控制算法
    """
    # --- 步骤 1: 分别检测左右摄像头的车道偏移 ---
    left_offset, left_conf = lane_center_offset(left_frame)
    right_offset, right_conf = lane_center_offset(right_frame)

    # --- 步骤 2: 融合两个摄像头的检测结果 ---
    left_valid = left_conf > 0.0
    right_valid = right_conf > 0.0

    if left_valid and right_valid:
        # 两个摄像头都检测到车道线 -> 加权融合
        offset = combine_offsets(left_offset, left_conf, right_offset, right_conf)
        lane_conf = clamp(max(left_conf, right_conf), 0.0, 1.0)
    elif left_valid:
        # 只有左摄像头检测到
        offset = left_offset
        lane_conf = clamp(left_conf, 0.0, 1.0)
    elif right_valid:
        # 只有右摄像头检测到
        offset = right_offset
        lane_conf = clamp(right_conf, 0.0, 1.0)
    else:
        # 两个摄像头都没检测到 -> 保持上一帧状态
        offset = 0.0
        lane_conf = 0.0

    # --- 步骤 3: 平滑滤波 ---
    if lane_conf > 0.0:
        filtered_offset = (
            OFFSET_SMOOTHING * filtered_offset
            + (1.0 - OFFSET_SMOOTHING) * offset
        )
        filtered_conf = (
            OFFSET_SMOOTHING * filtered_conf
            + (1.0 - OFFSET_SMOOTHING) * lane_conf
        )

    # --- 步骤 4: 计算转向 ---
    # 转向增益随偏移量增大而增大（急弯更灵敏）
    steer_boost = 1.0 + 0.6 * abs(filtered_offset)
    steering = clamp(
        -filtered_offset * STEER_GAIN * steer_boost,
        -1.0, 1.0,
    )

    # 如果置信度太低，保持上一帧的转向
    if lane_conf < MIN_CONFIDENCE:
        steering = last_steering * 0.9

    # 如果在直线上（偏移量很小），稍微回正
    if abs(filtered_offset) < STRAIGHT_DEADBAND:
        steering = steering * 0.4

    # --- 步骤 5: 转向平滑 ---
    steering = last_steering * STEER_SMOOTHING + steering * (1.0 - STEER_SMOOTHING)

    # --- 步骤 6: 计算速度和转向灯 ---
    speed = decide_speed(steering, lane_conf)
    signal = decide_turn_signal(steering)

    # --- 保存当前帧的灰度图供下一帧使用 ---
    new_left_gray = (
        cv2.cvtColor(left_frame, cv2.COLOR_BGR2GRAY)
        if left_frame is not None else prev_left_gray
    )
    new_right_gray = (
        cv2.cvtColor(right_frame, cv2.COLOR_BGR2GRAY)
        if right_frame is not None else prev_right_gray
    )

    return (
        steering, speed, signal,
        new_left_gray, new_right_gray,
        filtered_offset, filtered_conf, steering,
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  以下代码一般不需要修改 — Webots 设备初始化和主循环                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def get_device(robot, names):
    """
    安全地获取 Webots 设备，尝试多个可能的名称。

    参数:
        robot: Webots Robot 对象
        names: 可能的设备名称列表

    返回:
        找到的第一个设备，如果都没找到则返回 None
    """
    for name in names:
        try:
            dev = robot.getDevice(name)
        except Exception:
            dev = None
        if dev is not None:
            return dev
    return None


def set_indicator_with_driver(driver, signal: str) -> bool:
    """
    通过 Driver API 设置转向灯。

    参数:
        driver: Webots Driver 对象
        signal: "left", "right", 或 "off"

    返回:
        True 如果设置成功
    """
    set_indicator = getattr(driver, "setIndicator", None)
    if set_indicator is None:
        return False
    left_const = getattr(driver, "INDICATOR_LEFT", None)
    right_const = getattr(driver, "INDICATOR_RIGHT", None)
    off_const = getattr(driver, "INDICATOR_OFF", None)
    if left_const is None or right_const is None or off_const is None:
        return False
    if signal == "left":
        try:
            set_indicator(left_const)
        except (AttributeError, RuntimeError):
            return False
    elif signal == "right":
        try:
            set_indicator(right_const)
        except (AttributeError, RuntimeError):
            return False
    else:
        try:
            set_indicator(off_const)
        except (AttributeError, RuntimeError):
            return False
    return True


def init_indicator_leds(robot):
    """
    初始化转向灯 LED 设备。

    参数:
        robot: Webots Robot 对象

    返回:
        (left_led, right_led) 元组
    """
    left_led = get_device(
        robot,
        ["left_indicator", "left_signal", "left_blinker", "indicator_left"],
    )
    right_led = get_device(
        robot,
        ["right_indicator", "right_signal", "right_blinker", "indicator_right"],
    )
    return left_led, right_led


def set_indicator_with_leds(left_led, right_led, signal: str) -> None:
    """
    通过 LED 设备设置转向灯。

    参数:
        left_led: 左转向灯 LED 设备
        right_led: 右转向灯 LED 设备
        signal: "left", "right", 或 "off"
    """
    if left_led is None and right_led is None:
        return
    left_val = 1.0 if signal == "left" else 0.0
    right_val = 1.0 if signal == "right" else 0.0
    if left_led is not None:
        left_led.set(left_val)
    if right_led is not None:
        right_led.set(right_val)


def run() -> None:
    """
    主函数：初始化 Webots 设备并进入控制循环。

    这是整个控制器的入口点。它：
    1. 尝试创建 Driver 或 Robot 对象
    2. 初始化所有传感器（摄像头、GPS、罗盘）
    3. 初始化执行器（电机、转向）
    4. 进入主循环，每帧调用 compute_control()

    注意:
        此函数一般不需要修改。如果你需要添加新的传感器或执行器，
        可以在这里添加初始化代码。
    """
    # --- 步骤 1: 创建 Driver/Robot 对象 ---
    # 优先使用 Driver API（提供更高级的车辆控制接口）
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

    # --- 步骤 2: 初始化传感器 ---
    # 摄像头（必须）
    left_camera = get_device(robot, [LEFT_CAMERA_NAME])
    right_camera = get_device(robot, [RIGHT_CAMERA_NAME])

    if left_camera is None and right_camera is None:
        raise RuntimeError(
            "未找到摄像头！请确保 PROTO 文件中配置了 left_camera 和 right_camera。"
        )

    if left_camera is not None:
        left_camera.enable(timestep)
        print(f"[Controller] 左摄像头已启用: {LEFT_CAMERA_NAME}")
    if right_camera is not None:
        right_camera.enable(timestep)
        print(f"[Controller] 右摄像头已启用: {RIGHT_CAMERA_NAME}")

    # GPS（可选，用于位置感知）
    gps = get_device(robot, ["gps", "GPS"])
    if gps is not None:
        gps.enable(timestep)
        print("[Controller] GPS 已启用")

    # 罗盘（可选，用于方向感知）
    compass = get_device(robot, ["compass", "Compass"])
    if compass is not None:
        compass.enable(timestep)
        print("[Controller] 罗盘已启用")

    # --- 步骤 3: 初始化执行器 ---
    # 如果使用 Robot API，需要手动获取电机设备
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

    # 转向灯 LED
    left_indicator_led, right_indicator_led = (None, None)
    if not use_driver:
        left_indicator_led, right_indicator_led = init_indicator_leds(robot)

    # --- 步骤 4: 初始化状态变量 ---
    prev_left_gray: Optional[np.ndarray] = None
    prev_right_gray: Optional[np.ndarray] = None
    filtered_offset: float = 0.0
    filtered_conf: float = 0.0
    last_steering: float = 0.0

    print("[Controller] 初始化完成，进入控制循环...")

    # --- 步骤 5: 主控制循环 ---
    while (driver.step() if use_driver else robot.step(timestep)) != -1:
        # --- 获取摄像头图像 ---
        left_frame = camera_to_bgr(left_camera) if left_camera is not None else None
        right_frame = camera_to_bgr(right_camera) if right_camera is not None else None

        # 检查图像是否有效
        if right_frame is not None and not frame_has_lane_features(right_frame):
            right_frame = None
        if left_frame is None and right_frame is None:
            # 两个摄像头都无效，跳过这一帧
            continue

        # --- 计算控制输出 ---
        (
            steering, speed, signal,
            prev_left_gray, prev_right_gray,
            filtered_offset, filtered_conf, last_steering,
        ) = compute_control(
            left_frame,
            right_frame,
            prev_left_gray,
            prev_right_gray,
            filtered_offset,
            filtered_conf,
            last_steering,
        )

        # --- 应用控制 ---
        steer_angle = clamp(
            steering * MAX_STEER_ANGLE,
            -MAX_STEER_ANGLE,
            MAX_STEER_ANGLE,
        )

        if use_driver:
            # 使用 Driver API（推荐）
            driver.setCruisingSpeed(speed)
            driver.setSteeringAngle(steer_angle)
            if not set_indicator_with_driver(driver, signal):
                set_indicator_with_leds(
                    left_indicator_led, right_indicator_led, signal,
                )
        else:
            # 使用 Robot API（备选）
            if fl_steer is not None:
                fl_steer.setPosition(steer_angle)
            if fr_steer is not None:
                fr_steer.setPosition(steer_angle)
            if left_motor is not None and right_motor is not None:
                wheel_speed = speed / MAX_SPEED
                wheel_speed = clamp(wheel_speed, 0.0, 1.0)
                base = 8000.0 * wheel_speed
                diff = steering * 4000.0
                left_motor.setVelocity(base + diff)
                right_motor.setVelocity(base - diff)
            set_indicator_with_leds(
                left_indicator_led, right_indicator_led, signal,
            )

    print("[Controller] 控制循环结束")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SDK 沙箱入口 — 本地测试与线上提交所需的 control() 函数                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# 帧间状态（跨调用持久化）
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
            steering ∈ [-1, 1]  负值左转，正值右转
            speed    ∈ [0, 1]   归一化速度
    """
    s = _state

    left_frame = left_img if (left_img is not None and left_img.size > 0) else None
    right_frame = right_img if (right_img is not None and right_img.size > 0) else None

    (
        steering, speed, _signal,
        s["prev_left_gray"], s["prev_right_gray"],
        s["filtered_offset"], s["filtered_conf"], s["last_steering"],
    ) = compute_control(
        left_frame,
        right_frame,
        s["prev_left_gray"],
        s["prev_right_gray"],
        s["filtered_offset"],
        s["filtered_conf"],
        s["last_steering"],
    )

    # 将速度从 km/h 归一化到 [0, 1]
    speed_normalized = clamp(speed / MAX_SPEED, 0.0, 1.0)

    return float(steering), float(speed_normalized)


if __name__ == "__main__":
    run()

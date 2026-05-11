"""TeslaModel3 controller: stereo cameras + OpenCV lane detection.

This controller reads left/right cameras named "left_camera" and "right_camera",
performs a simple lane detection using OpenCV, and outputs steering, speed, and
turn-signal decisions. It is designed for the TeslaModel3 node in Webots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

import cv2
import numpy as np


LEFT_CAMERA_NAME = "left_camera"
RIGHT_CAMERA_NAME = "right_camera"

BASE_SPEED = 12.0
MIN_SPEED = 4.0
MAX_SPEED = 22.0
SPEED_TURN_PENALTY = 0.65
CONF_SPEED_BOOST = 0.35
STEER_GAIN = 1.4
MAX_STEER_ANGLE = 0.5
SIGNAL_THRESHOLD = 0.25
FULL_CONFIDENCE_LINE_COUNT = 8.0


@dataclass
class VisionState:
    prev_left_gray: Optional[np.ndarray] = None
    prev_right_gray: Optional[np.ndarray] = None


@dataclass
class ControlDecision:
    steering: float
    speed: float
    signal: str  # "left", "right", "off"


def camera_to_bgr(camera) -> Optional[np.ndarray]:
    width = camera.getWidth()
    height = camera.getHeight()
    image = camera.getImage()
    if image is None:
        return None
    buffer = np.frombuffer(image, np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(buffer, cv2.COLOR_BGRA2BGR)


def preprocess_edges(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 60, 160)
    return edges


def region_of_interest(edges: np.ndarray) -> np.ndarray:
    height, width = edges.shape
    mask = np.zeros_like(edges)
    polygon = np.array(
        [
            [0, height],
            [width, height],
            [int(width * 0.62), int(height * 0.55)],
            [int(width * 0.38), int(height * 0.55)],
        ],
        np.int32,
    )
    cv2.fillPoly(mask, [polygon], 255)
    return cv2.bitwise_and(edges, mask)


def average_lane_lines(lines: Optional[np.ndarray]) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    if lines is None:
        return None, None
    left_lines = []
    right_lines = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if x2 == x1:
            continue
        slope = (y2 - y1) / (x2 - x1)
        if abs(slope) < 0.5:
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
    if frame is None:
        return 0.0, 0.0
    height, width = frame.shape[:2]
    edges = preprocess_edges(frame)
    roi = region_of_interest(edges)
    lines = cv2.HoughLinesP(roi, 2, np.pi / 180, 50, minLineLength=40, maxLineGap=120)
    line_count = 0 if lines is None else len(lines)
    left, right = average_lane_lines(lines)
    if left is None or right is None:
        return 0.0, 0.0

    y_bottom = height
    y_top = int(height * 0.6)

    def line_x(slope: float, intercept: float, y: int) -> int:
        return int((y - intercept) / slope)

    left_x_bottom = line_x(left[0], left[1], y_bottom)
    right_x_bottom = line_x(right[0], right[1], y_bottom)
    lane_center = (left_x_bottom + right_x_bottom) / 2.0
    image_center = width / 2.0
    offset = (lane_center - image_center) / image_center
    confidence = min(1.0, line_count / FULL_CONFIDENCE_LINE_COUNT)
    return float(offset), float(confidence)


def combine_offsets(left_offset: float, left_conf: float, right_offset: float, right_conf: float) -> float:
    total = left_conf + right_conf
    if total <= 0.0:
        return 0.0
    return float((left_offset * left_conf + right_offset * right_conf) / total)


def clamp(value: float, min_v: float, max_v: float) -> float:
    return float(max(min_v, min(max_v, value)))


def decide_turn_signal(steering: float) -> str:
    if steering < -SIGNAL_THRESHOLD:
        return "left"
    if steering > SIGNAL_THRESHOLD:
        return "right"
    return "off"


def decide_speed(steering: float, confidence: float) -> float:
    base = BASE_SPEED * (1.0 - SPEED_TURN_PENALTY * abs(steering))
    boosted = base + (MAX_SPEED - base) * CONF_SPEED_BOOST * confidence
    return clamp(boosted, MIN_SPEED, MAX_SPEED)


def compute_control(
    left_frame: Optional[np.ndarray],
    right_frame: Optional[np.ndarray],
) -> ControlDecision:
    left_offset, left_conf = lane_center_offset(left_frame)
    right_offset, right_conf = lane_center_offset(right_frame)

    offset = combine_offsets(left_offset, left_conf, right_offset, right_conf)
    lane_conf = clamp(max(left_conf, right_conf), 0.0, 1.0)

    steering = clamp(-offset * STEER_GAIN, -1.0, 1.0)
    speed = decide_speed(steering, lane_conf)
    signal = decide_turn_signal(steering)
    return ControlDecision(steering=steering, speed=speed, signal=signal)


def get_device(robot, names: Iterable[str]):
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
    if signal == "left":
        set_indicator(left_const)
    elif signal == "right":
        set_indicator(right_const)
    else:
        set_indicator(off_const)
    return True


def set_indicator_with_leds(robot, signal: str) -> None:
    left_led = get_device(robot, ["left_indicator", "left_signal", "left_blinker", "indicator_left"]) 
    right_led = get_device(robot, ["right_indicator", "right_signal", "right_blinker", "indicator_right"]) 
    if left_led is None and right_led is None:
        return
    left_val = 1.0 if signal == "left" else 0.0
    right_val = 1.0 if signal == "right" else 0.0
    if left_led is not None:
        left_led.set(left_val)
    if right_led is not None:
        right_led.set(right_val)


def run() -> None:
    try:
        from vehicle import Driver  # type: ignore
        driver = Driver()
        robot = driver
        use_driver = True
    except Exception:
        from controller import Robot  # type: ignore
        driver = Robot()
        robot = driver
        use_driver = False

    timestep = int(robot.getBasicTimeStep())

    left_camera = get_device(robot, [LEFT_CAMERA_NAME])
    right_camera = get_device(robot, [RIGHT_CAMERA_NAME])

    if left_camera is None and right_camera is None:
        raise RuntimeError("No cameras found for Tesla controller.")

    if left_camera is not None:
        left_camera.enable(timestep)
    if right_camera is not None:
        right_camera.enable(timestep)

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

    while robot.step(timestep) != -1:
        left_frame = camera_to_bgr(left_camera) if left_camera is not None else None
        right_frame = camera_to_bgr(right_camera) if right_camera is not None else None
        if left_frame is None and right_frame is None:
            continue

        decision = compute_control(left_frame, right_frame)
        steer_angle = clamp(decision.steering * MAX_STEER_ANGLE, -MAX_STEER_ANGLE, MAX_STEER_ANGLE)

        if use_driver:
            driver.setCruisingSpeed(decision.speed)
            driver.setSteeringAngle(steer_angle)
            if not set_indicator_with_driver(driver, decision.signal):
                set_indicator_with_leds(robot, decision.signal)
        else:
            if fl_steer is not None:
                fl_steer.setPosition(steer_angle)
            if fr_steer is not None:
                fr_steer.setPosition(steer_angle)
            if left_motor is not None and right_motor is not None:
                wheel_speed = decision.speed / MAX_SPEED
                wheel_speed = clamp(wheel_speed, 0.0, 1.0)
                base = 8000.0 * wheel_speed
                diff = decision.steering * 4000.0
                left_motor.setVelocity(base + diff)
                right_motor.setVelocity(base - diff)
            set_indicator_with_leds(robot, decision.signal)


if __name__ == "__main__":
    run()

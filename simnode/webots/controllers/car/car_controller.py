"""TeslaModel3 controller for simnode — in-process student-code loading + OpenCV fallback.

Matches the SDK controller architecture (sdk/webots/controllers/car/car_controller.py):
- Uses importlib to load student control() in-process (zero pipe latency).
- Built-in OpenCV lane-detection controller as fallback when no student code.
- Reads left_camera / right_camera from robot devices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, List

import math
import os
import json

import cv2
import numpy as np


LEFT_CAMERA_NAME = "left_camera"
RIGHT_CAMERA_NAME = "right_camera"

BASE_SPEED = 12.0
MIN_SPEED = 4.0
MAX_SPEED = 22.0
SPEED_TURN_PENALTY = 0.65
CONF_SPEED_BOOST = 0.35
STEER_GAIN = 2.8
MAX_STEER_ANGLE = 0.70
SIGNAL_THRESHOLD = 0.25
FULL_CONFIDENCE_LINE_COUNT = 8.0
MIN_EDGE_DENSITY = 0.003
GRAY_CHANGE_THRESHOLD = 1.5
STRAIGHT_DEADBAND = 0.02
OFFSET_SMOOTHING = 0.7
STEER_SMOOTHING = 0.6
MIN_CONFIDENCE = 0.15
MOTOR_MAX = 0.80           # hard clamp to prevent Webots "too big requested position" warning


@dataclass
class VisionState:
    prev_left_gray: Optional[np.ndarray] = None
    prev_right_gray: Optional[np.ndarray] = None
    filtered_offset: float = 0.0
    filtered_conf: float = 0.0
    last_steering: float = 0.0


@dataclass
class ControlDecision:
    steering: float
    speed: float
    signal: str  # "left", "right", "off"


# ── Camera helpers ──────────────────────────────────────────────────────

def camera_to_bgr(camera) -> Optional[np.ndarray]:
    if camera is None:
        return None
    image = camera.getImage()
    if image is None:
        return None
    w = camera.getWidth()
    h = camera.getHeight()
    buffer = np.frombuffer(image, np.uint8).reshape((h, w, 4))
    return cv2.cvtColor(buffer, cv2.COLOR_BGRA2BGR)


# ── Lane detection ──────────────────────────────────────────────────────

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
            [int(width * 0.60), int(height * 0.65)],
            [int(width * 0.40), int(height * 0.65)],
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
        if abs(slope) < 0.6:
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
    def line_x(slope, intercept, y):
        return int((y - intercept) / slope)
    left_x = line_x(left[0], left[1], y_bottom)
    right_x = line_x(right[0], right[1], y_bottom)
    lane_center = (left_x + right_x) / 2.0
    image_center = width / 2.0
    offset = (lane_center - image_center) / image_center
    confidence = min(1.0, line_count / FULL_CONFIDENCE_LINE_COUNT)
    return float(offset), float(confidence)


def frame_has_lane_features(frame: Optional[np.ndarray]) -> bool:
    if frame is None:
        return False
    edges = preprocess_edges(frame)
    roi = region_of_interest(edges)
    edge_density = float(np.count_nonzero(roi)) / float(roi.size)
    return edge_density >= MIN_EDGE_DENSITY


def roi_mask(height: int, width: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    polygon = np.array(
        [
            [0, height],
            [width, height],
            [int(width * 0.60), int(height * 0.65)],
            [int(width * 0.40), int(height * 0.65)],
        ],
        np.int32,
    )
    cv2.fillPoly(mask, [polygon], 255)
    return mask


def grayscale_change(prev_gray: Optional[np.ndarray], frame: Optional[np.ndarray]) -> float:
    if prev_gray is None or frame is None:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if prev_gray.shape != gray.shape:
        return 0.0
    diff = cv2.absdiff(prev_gray, gray)
    mask = roi_mask(gray.shape[0], gray.shape[1])
    roi = diff[mask > 0]
    if roi.size == 0:
        return 0.0
    return float(np.mean(roi))


def combine_offsets(lo: float, lc: float, ro: float, rc: float) -> float:
    total = lc + rc
    if total <= 0.0:
        return 0.0
    return float((lo * lc + ro * rc) / total)


def clamp(value: float, min_v: float, max_v: float) -> float:
    return float(max(min_v, min(max_v, value)))


# ── Decision logic ──────────────────────────────────────────────────────

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
    state: VisionState,
) -> ControlDecision:
    lo, lc = lane_center_offset(left_frame)
    ro, rc = lane_center_offset(right_frame)

    lch = grayscale_change(state.prev_left_gray, left_frame)
    rch = grayscale_change(state.prev_right_gray, right_frame)
    change_metric = max(lch, rch)

    lv = lc > 0.0
    rv = rc > 0.0
    if lv and rv:
        offset = combine_offsets(lo, lc, ro, rc)
        lane_conf = clamp(max(lc, rc), 0.0, 1.0)
    elif lv:
        offset = lo
        lane_conf = clamp(lc, 0.0, 1.0)
    elif rv:
        offset = ro
        lane_conf = clamp(rc, 0.0, 1.0)
    else:
        offset = 0.0
        lane_conf = 0.0

    if lane_conf > 0.0:
        state.filtered_offset = (
            OFFSET_SMOOTHING * state.filtered_offset + (1.0 - OFFSET_SMOOTHING) * offset
        )
        state.filtered_conf = (
            OFFSET_SMOOTHING * state.filtered_conf + (1.0 - OFFSET_SMOOTHING) * lane_conf
        )

    steer_boost = 1.0 + 0.6 * abs(state.filtered_offset)
    steering = clamp(-state.filtered_offset * STEER_GAIN * steer_boost, -1.0, 1.0)

    if lane_conf < MIN_CONFIDENCE:
        steering = state.last_steering * 0.9
    elif change_metric < GRAY_CHANGE_THRESHOLD:
        steering = clamp(steering * 0.4, -1.0, 1.0)
        if abs(state.filtered_offset) < STRAIGHT_DEADBAND:
            steering = 0.0

    steering = state.last_steering * STEER_SMOOTHING + steering * (1.0 - STEER_SMOOTHING)
    state.last_steering = steering

    speed = decide_speed(steering, lane_conf)
    signal = decide_turn_signal(steering)
    return ControlDecision(steering=steering, speed=speed, signal=signal)


# ── Device helpers ──────────────────────────────────────────────────────

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
        try: set_indicator(left_const)
        except (AttributeError, RuntimeError): return False
    elif signal == "right":
        try: set_indicator(right_const)
        except (AttributeError, RuntimeError): return False
    else:
        try: set_indicator(off_const)
        except (AttributeError, RuntimeError): return False
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


# ── Student-code loader (in-process, same pattern as SDK) ───────────────

def _load_student_control_fn(config_path: str, my_node: str):
    """Load student control() in-process via importlib. Returns None on failure."""
    try:
        with open(config_path, encoding='utf-8') as f:
            cfg = json.load(f)
        my_entry = next(
            (c for c in cfg.get('cars', []) if c.get('car_slot') == my_node),
            None,
        )
        if my_entry is None:
            return None
        student_path = my_entry.get('code_path')
        if not student_path:
            return None
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("_student_ctrl", student_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, 'control', None)
        if callable(fn):
            print(f"[car_controller] 已加载学生控制器: {student_path}")
            return fn
        print(f"[car_controller][warn] {student_path} 中未找到 control()，使用内置逻辑")
        return None
    except Exception as e:
        print(f"[car_controller][warn] 加载学生控制器失败: {e}，使用内置逻辑")
        return None


# ── Main controller ─────────────────────────────────────────────────────

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

    config_path = os.environ.get('RACE_CONFIG_PATH')
    student_control_fn = None
    disqualified = False

    if config_path:
        try:
            with open(config_path, encoding='utf-8') as f:
                cfg = json.load(f)
            my_node = robot.getName()
            if not any(c.get('car_slot') == my_node for c in cfg.get('cars', [])):
                while (driver.step() if use_driver else robot.step(timestep)) != -1:
                    pass
                return
            student_control_fn = _load_student_control_fn(config_path, my_node)
        except Exception:
            pass

    left_camera = get_device(robot, [LEFT_CAMERA_NAME])
    right_camera = get_device(robot, [RIGHT_CAMERA_NAME])
    gps = get_device(robot, ["gps", "GPS"])
    compass = get_device(robot, ["compass", "Compass"])

    if left_camera is None and right_camera is None:
        raise RuntimeError("No cameras found for Tesla controller.")

    if left_camera is not None:
        left_camera.enable(timestep)
    if right_camera is not None:
        right_camera.enable(timestep)
    if gps is not None:
        gps.enable(timestep)
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

    vision_state = VisionState()
    _sim_timestamp: float = 0.0

    while (driver.step() if use_driver else robot.step(timestep)) != -1:
        _sim_timestamp += timestep / 1000.0

        # IPC from supervisor (stop / disqualify)
        custom_data = robot.getCustomData()
        if custom_data:
            try:
                cmd = json.loads(custom_data)
                if cmd.get('cmd') == 'disqualify':
                    disqualified = True
                elif cmd.get('cmd') == 'stop':
                    # Supervisor requested permanent stop (race finished)
                    disqualified = True  # reuse death path — brakes+idle
            except (json.JSONDecodeError, ValueError):
                pass

        if disqualified:
            if use_driver:
                driver.setCruisingSpeed(0.0)
                driver.setSteeringAngle(0.0)
            else:
                if left_motor is not None:
                    left_motor.setVelocity(0.0)
                if right_motor is not None:
                    right_motor.setVelocity(0.0)
                if fl_steer is not None:
                    fl_steer.setPosition(0.0)
                if fr_steer is not None:
                    fr_steer.setPosition(0.0)
            continue

        left_frame = camera_to_bgr(left_camera) if left_camera is not None else None
        right_frame = camera_to_bgr(right_camera) if right_camera is not None else None
        if left_frame is None and right_frame is None:
            continue

        # ── 学生控制器（进程内调用，零延迟，与 SDK 一致）────────────────
        if student_control_fn is not None:
            _left = left_frame if left_frame is not None else np.zeros((480, 640, 3), np.uint8)
            _right = right_frame if right_frame is not None else np.zeros((480, 640, 3), np.uint8)
            try:
                result = student_control_fn(_left, _right, _sim_timestamp)
                raw_steering = float(result[0])
                raw_speed    = float(result[1])
            except Exception as e:
                print(f"[car_controller][warn] 学生 control() 出错: {e}")
                raw_steering, raw_speed = 0.0, 0.0
            steer_angle = clamp(raw_steering * MOTOR_MAX, -MOTOR_MAX, MOTOR_MAX)
            if use_driver:
                driver.setCruisingSpeed(clamp(raw_speed, 0.0, 1.0) * MAX_SPEED)
                driver.setSteeringAngle(steer_angle)
            else:
                if fl_steer is not None:
                    fl_steer.setPosition(steer_angle)
                if fr_steer is not None:
                    fr_steer.setPosition(steer_angle)
                if left_motor is not None and right_motor is not None:
                    base = 8000.0 * clamp(raw_speed, 0.0, 1.0)
                    diff = raw_steering * 4000.0
                    left_motor.setVelocity(base + diff)
                    right_motor.setVelocity(base - diff)
            continue  # 跳过内置逻辑

        # ── 无学生代码时静止不动 ──────────────────────────────────────
        if use_driver:
            driver.setCruisingSpeed(0.0)
            driver.setSteeringAngle(0.0)
        else:
            if left_motor is not None:
                left_motor.setVelocity(0.0)
            if right_motor is not None:
                right_motor.setVelocity(0.0)
            if fl_steer is not None:
                fl_steer.setPosition(0.0)
            if fr_steer is not None:
                fr_steer.setPosition(0.0)
        continue


if __name__ == "__main__":
    run()

import importlib.util
from pathlib import Path

import cv2
import numpy as np

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "sdk"
    / "webots"
    / "controllers"
    / "tesla_controller.py"
)
spec = importlib.util.spec_from_file_location("tesla_controller", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load tesla_controller module")
tesla_controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tesla_controller)

compute_control = tesla_controller.compute_control


def synthetic_lane(width: int, height: int, shift: int = 0) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    left_bottom = (int(width * 0.35) + shift, height - 1)
    left_top = (int(width * 0.45) + shift, int(height * 0.6))
    right_bottom = (int(width * 0.65) + shift, height - 1)
    right_top = (int(width * 0.55) + shift, int(height * 0.6))
    cv2.line(image, left_bottom, left_top, (255, 255, 255), 6)
    cv2.line(image, right_bottom, right_top, (255, 255, 255), 6)
    return image


def test_center_lane_has_small_steer():
    frame = synthetic_lane(640, 480, shift=0)
    decision = compute_control(frame, frame)
    assert abs(decision.steering) < 0.2
    assert decision.signal == "off"


def test_shift_right_lane_turns_right():
    frame = synthetic_lane(640, 480, shift=40)
    decision = compute_control(frame, frame)
    assert decision.steering > 0.05
    assert decision.signal == "right"


def test_shift_left_lane_turns_left():
    frame = synthetic_lane(640, 480, shift=-40)
    decision = compute_control(frame, frame)
    assert decision.steering < -0.05
    assert decision.signal == "left"

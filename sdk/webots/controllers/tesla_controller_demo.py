"""Small demo harness for tesla_controller lane detection (no Webots required)."""

from __future__ import annotations

import cv2
import numpy as np

from tesla_controller import ControlDecision, compute_control


def synthetic_lane(width: int, height: int, shift: int = 0) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    left_bottom = (int(width * 0.35) + shift, height - 1)
    left_top = (int(width * 0.45) + shift, int(height * 0.6))
    right_bottom = (int(width * 0.65) + shift, height - 1)
    right_top = (int(width * 0.55) + shift, int(height * 0.6))
    cv2.line(image, left_bottom, left_top, (255, 255, 255), 6)
    cv2.line(image, right_bottom, right_top, (255, 255, 255), 6)
    return image


def run_case(label: str, shift: int) -> ControlDecision:
    frame = synthetic_lane(640, 480, shift=shift)
    decision = compute_control(frame, frame)
    print(f"{label}: steering={decision.steering:.3f} speed={decision.speed:.2f} signal={decision.signal}")
    return decision


if __name__ == "__main__":
    run_case("center", 0)
    run_case("left_shift", -40)
    run_case("right_shift", 40)

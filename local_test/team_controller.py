"""User-editable controller entry point for `local_test`.

How to replace the movement logic:
- Edit this file only.
- Keep a function named `control(left_img, right_img, timestamp)`.
- Return `(steering, speed)` where both values are floats:
  - steering: -1.0 ~ 1.0
  - speed: 0.0 ~ 1.0

The car controller in `local_test/webots/controllers/car/car.py` will load
this file automatically if it exists.
"""

from __future__ import annotations

import numpy as np


def control(left_img: np.ndarray, right_img: np.ndarray, timestamp: float) -> tuple[float, float]:
    # Example: simple lane-following using the left camera.
    # You can replace this with your own algorithm.
    gray = left_img.mean(axis=2)
    roi = gray[int(gray.shape[0] * 0.55): int(gray.shape[0] * 0.95)]
    mask = roi < 90
    if mask.sum() < 80:
        return 0.0, 0.3

    cols = mask.sum(axis=0)
    xs = np.arange(gray.shape[1])
    cx = float((xs * cols).sum() / cols.sum())
    lane_error = (cx - gray.shape[1] / 2.0) / (gray.shape[1] / 2.0)
    steering = float(np.clip(lane_error * 1.2, -1.0, 1.0))
    speed = float(np.clip(0.85 * (1.0 - 0.7 * abs(steering)), 0.2, 1.0))
    return steering, speed


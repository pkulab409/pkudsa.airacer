"""A simple example controller that students can run locally.

This controller is intentionally lightweight and uses only NumPy so it will
work in environments without OpenCV. It provides a basic center-of-brightness
steering heuristic and a speed that decreases with sharper turns.

The function `control(left_img, right_img, timestamp)` matches the required
interface used by the sandbox runner.
"""

from typing import Tuple
import numpy as np


IMG_H, IMG_W = 480, 640


def _brightness_center(img: np.ndarray) -> float:
    """Return x-coordinate of brightness centre (0..IMG_W-1).

    img: uint8 BGR image (H, W, 3)
    """
    # Convert to grayscale by average of channels — cheap and effective here
    gray = img.mean(axis=2)
    # Column sums -> brightness per x
    col = gray.sum(axis=0)
    xs = np.arange(col.shape[0])
    total = col.sum()
    if total == 0:
        return IMG_W / 2
    cx = (xs * col).sum() / total
    return float(cx)


def control(left_img: np.ndarray, right_img: np.ndarray, timestamp: float) -> Tuple[float, float]:
    """Compute steering and speed from stereo frames.

    A simple heuristic: compute brightness centres in the left and right cams,
    average them to estimate track center, compute normalized error, and map
    that to steering. Speed is reduced when steering magnitude is large.
    """
    try:
        # Defensive checks (will raise if shapes are unexpected)
        assert left_img.shape == (IMG_H, IMG_W, 3)
        assert right_img.shape == (IMG_H, IMG_W, 3)

        cx_l = _brightness_center(left_img)
        cx_r = _brightness_center(right_img)
        cx = 0.5 * (cx_l + cx_r)

        err = (cx - (IMG_W / 2)) / (IMG_W / 2)  # normalized: -1..1
        # steering: negative -> turn left, positive -> turn right
        steering = float(np.clip(err * 0.9, -1.0, 1.0))

        # simple speed policy: slow down on sharp turns
        base_speed = 0.7
        speed = float(max(0.0, min(1.0, base_speed * (1.0 - abs(steering)))))
    except Exception:
        # On any failure, be safe: stop
        steering, speed = 0.0, 0.0

    return steering, speed


if __name__ == "__main__":
    # Quick smoke test: create blank frames and call control
    l = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    r = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    print(control(l, r, 0.0))


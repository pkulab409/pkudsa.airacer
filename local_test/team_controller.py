"""A minimal local controller that drives straight at full speed.

The function `control(left_img, right_img, timestamp)` matches the required
interface used by the sandbox runner.
"""

from typing import Tuple
import numpy as np


IMG_H, IMG_W = 480, 640


def control(left_img: np.ndarray, right_img: np.ndarray, timestamp: float) -> Tuple[float, float]:
    """Drive straight at full speed.

    Returns steering=0.0 and speed=1.0 so the car keeps going forward.
    """
    steering = 0.0
    speed_norm = 1.0


    return steering, speed_norm


if __name__ == "__main__":
    # Quick smoke test: create blank frames and call control
    l = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    r = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    print(control(l, r, 0.0))


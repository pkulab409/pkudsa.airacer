"""Official team controller template.

This file is intended as the minimal, ready-to-run template shipped with the
course. It shows the required function signature and documents image formats,
value ranges and performance constraints.

Notes for students:
- Your module must expose a callable `control(left_img, right_img, timestamp)`.
- `left_img` / `right_img` are NumPy arrays with shape (480, 640, 3), dtype=uint8,
  in BGR channel order (row-major). Do not rely on extra channels.
- `timestamp` is a read-only float (seconds).
- The function must return `(steering, speed)` where steering ∈ [-1.0, 1.0]
  (negative = left, positive = right) and speed ∈ [0.0, 1.0].
- Each call is expected to complete fast (the Webots-side sandbox uses a
  20 ms read timeout; excessive CPU or blocking calls will cause penalties).

Allowed libraries in the sandbox: numpy, cv2 (optional), math, collections,
heapq, functools, itertools. Network / filesystem / threading and other
dangerous modules are blocked by the sandbox import hook.

Use `sdk/validate_controller.py` to run a local pre-submission check that mirrors
the server-side validation.
"""

import numpy as np


def control(left_img: np.ndarray, right_img: np.ndarray, timestamp: float) -> tuple[float, float]:
    """Minimal straight-driving controller.

    This template returns a small constant forward speed and zero steering so
    that an empty submission behaves reasonably in the simulator.

    Implement more advanced logic in `sdk/example_controller.py` or your own
    file and validate it with `python sdk/validate_controller.py --code-path <path>`.
    """

    # left_img and right_img are available as (480, 640, 3) uint8 BGR arrays.
    # Keep logic lightweight — avoid heavy allocations every frame.
    steering = 0.0
    speed = 0.5
    return steering, speed

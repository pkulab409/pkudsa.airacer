"""Minimal self-contained car controller for local_test.

This controller is intentionally simple:
- It reads `RACE_CONFIG_PATH` if available.
- Only the car whose `car_slot` matches the Webots node name moves.
- Other cars stay stopped, which avoids multiple active cars in the demo.
- The active car follows the lane using a simple grayscale heuristic over the
  left camera image (no OpenCV required).
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import numpy as np
from controller import Robot


IMG_H, IMG_W = 480, 640
WHEEL_MAX = 10.0
ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_TEAM_CONTROLLER = ROOT_DIR / "team_controller.py"


def _load_config() -> dict:
    path = os.environ.get("RACE_CONFIG_PATH", "race_config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"cars": []}


def _find_my_config(cfg: dict, node_name: str) -> dict | None:
    for c in cfg.get("cars", []):
        if c.get("car_slot") == node_name:
            return c
    return None


def _image_to_gray(cam) -> np.ndarray:
    raw = cam.getImage()
    arr = np.frombuffer(raw, dtype=np.uint8).reshape((IMG_H, IMG_W, 4))
    return arr[:, :, :3].mean(axis=2)


def _image_to_bgr(cam) -> np.ndarray:
    raw = cam.getImage()
    arr = np.frombuffer(raw, dtype=np.uint8).reshape((IMG_H, IMG_W, 4))
    return arr[:, :, :3].copy()


def _estimate_lane_center(gray: np.ndarray) -> float | None:
    # Road is typically darker than the surrounding terrain. We use a simple
    # threshold and compute the weighted centroid of dark pixels in the lower
    # part of the image.
    roi = gray[int(IMG_H * 0.55): int(IMG_H * 0.95)]
    mask = roi < 90
    count = int(mask.sum())
    if count < 80:
        return None
    cols = mask.sum(axis=0)
    if cols.sum() == 0:
        return None
    xs = np.arange(IMG_W)
    cx = float((xs * cols).sum() / cols.sum())
    return cx


def _set_motor_velocity(left_motor, right_motor, speed: float, steering: float) -> None:
    v = speed * WHEEL_MAX
    diff = steering * WHEEL_MAX * 0.5
    left_motor.setVelocity(max(-WHEEL_MAX, min(WHEEL_MAX, v + diff)))
    right_motor.setVelocity(max(-WHEEL_MAX, min(WHEEL_MAX, v - diff)))


def _load_custom_control():
    """Load user-defined `control()` from `local_test/team_controller.py`.

    Priority:
      1. `LOCAL_TEST_TEAM_CONTROLLER` env var if set
      2. `local_test/team_controller.py` if it exists

    The file must define: `control(left_img, right_img, timestamp) -> (steering, speed)`.
    """
    custom_path = os.environ.get("LOCAL_TEST_TEAM_CONTROLLER")
    candidate = Path(custom_path).expanduser() if custom_path else DEFAULT_TEAM_CONTROLLER
    if not candidate.is_file():
        return None

    spec = importlib.util.spec_from_file_location("local_test_team_controller", str(candidate))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    control_fn = getattr(module, "control", None)
    if callable(control_fn):
        print(f"[car] loaded custom control from: {candidate}")
        return control_fn
    return None


robot = Robot()
timestep = int(robot.getBasicTimeStep())
node_name = robot.getName()
cfg = _load_config()
my_cfg = _find_my_config(cfg, node_name)
custom_control = _load_custom_control()

left_motor = robot.getDevice("left_motor")
right_motor = robot.getDevice("right_motor")
left_motor.setPosition(float("inf"))
right_motor.setPosition(float("inf"))
left_motor.setVelocity(0.0)
right_motor.setVelocity(0.0)

left_cam = robot.getDevice("left_camera")
right_cam = robot.getDevice("right_camera")
left_cam.enable(timestep)
right_cam.enable(timestep)

# If this node is not the configured car, keep it idle so only car_1 moves.
if my_cfg is None:
    while robot.step(timestep) != -1:
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
    raise SystemExit(0)

last_steering = 0.0
last_speed = 0.45

while robot.step(timestep) != -1:
    try:
        if custom_control is not None:
            left_img = _image_to_bgr(left_cam)
            right_img = _image_to_bgr(right_cam)
            steering, speed = custom_control(left_img, right_img, robot.getTime())
            steering = float(max(-1.0, min(1.0, steering)))
            speed = float(max(0.0, min(1.0, speed)))
        else:
            gray = _image_to_gray(left_cam)
            cx = _estimate_lane_center(gray)
            if cx is None:
                steering = last_steering * 0.95
                speed = 0.35
            else:
                lane_error = (cx - IMG_W / 2.0) / (IMG_W / 2.0)
                steering = float(np.clip(lane_error * 1.2, -1.0, 1.0))
                speed = float(np.clip(0.85 * (1.0 - 0.7 * abs(steering)), 0.2, 1.0))

        last_steering = steering
        last_speed = speed
        _set_motor_velocity(left_motor, right_motor, speed, steering)
    except Exception:
        # On any failure, slow down but keep the car alive.
        _set_motor_velocity(left_motor, right_motor, last_speed * 0.6, last_steering * 0.5)



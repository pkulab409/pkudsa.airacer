"""Minimal self-contained car controller for local_test.

This controller is intentionally simple:
- It reads `RACE_CONFIG_PATH` if available.
- Only the car whose `car_slot` matches the Webots node name moves.
- Other cars stay stopped, which avoids multiple active cars in the demo.
- The active car follows the lane using a simple grayscale heuristic over the
  left camera image (no OpenCV required).
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
from controller import Robot


IMG_H, IMG_W = 480, 640
WHEEL_SPEED_SCALE = float(os.environ.get("CAR_WHEEL_SPEED_SCALE", "50.0"))
WHEEL_TURN_SCALE = float(os.environ.get("CAR_WHEEL_TURN_SCALE", "75.0"))
WHEEL_CMD_LIMIT = float(os.environ.get("CAR_WHEEL_CMD_LIMIT", "100.0"))
DISPLAY_PANEL_W = int(os.environ.get("CAR_DISPLAY_PANEL_W", "160"))
DISPLAY_PANEL_H = int(os.environ.get("CAR_DISPLAY_PANEL_H", "120"))
DISPLAY_SCALE = int(os.environ.get("CAR_DISPLAY_SCALE", "2"))
DISPLAY_UPDATE_STEPS = int(os.environ.get("CAR_DISPLAY_UPDATE_STEPS", "3"))


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
    v = speed * WHEEL_SPEED_SCALE
    diff = steering * WHEEL_TURN_SCALE
    left_motor.setVelocity(max(-WHEEL_CMD_LIMIT, min(WHEEL_CMD_LIMIT, v + diff)))
    right_motor.setVelocity(max(-WHEEL_CMD_LIMIT, min(WHEEL_CMD_LIMIT, v - diff)))


def _render_camera_pair(display, left_img: np.ndarray, right_img: np.ndarray) -> None:
    """Render left/right camera views side-by-side on a Webots Display."""
    try:
        display.setColor(0x000000)
        display.fillRectangle(0, 0, DISPLAY_PANEL_W * 2, DISPLAY_PANEL_H)

        sample_w = max(1, IMG_W // (DISPLAY_PANEL_W // DISPLAY_SCALE))
        sample_h = max(1, IMG_H // (DISPLAY_PANEL_H // DISPLAY_SCALE))
        src_w = DISPLAY_PANEL_W // DISPLAY_SCALE
        src_h = DISPLAY_PANEL_H // DISPLAY_SCALE

        for panel_idx, img in enumerate((left_img, right_img)):
            x_off = panel_idx * DISPLAY_PANEL_W
            for sy in range(src_h):
                src_y = min(IMG_H - 1, sy * sample_h)
                dst_y = sy * DISPLAY_SCALE
                for sx in range(src_w):
                    src_x = min(IMG_W - 1, sx * sample_w)
                    b, g, r = img[src_y, src_x, :3]
                    display.setColor((int(r) << 16) | (int(g) << 8) | int(b))
                    display.fillRectangle(
                        x_off + sx * DISPLAY_SCALE,
                        dst_y,
                        DISPLAY_SCALE,
                        DISPLAY_SCALE,
                    )
    except Exception:
        pass


robot = Robot()
timestep = int(robot.getBasicTimeStep())
node_name = robot.getName()
cfg = _load_config()
my_cfg = _find_my_config(cfg, node_name)

# Try to import a team-provided controller (team_controller.py) from the
# local_test directory. If present, prefer its `control` function. This
# allows students to only edit `local_test/team_controller.py` and have
# the `car.py` delegate to it.
try:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
    from team_controller import control
except Exception:
    control = None

left_motor = robot.getDevice("left_motor")
right_motor = robot.getDevice("right_motor")
left_motor.setPosition(float("inf"))
right_motor.setPosition(float("inf"))
left_motor.setVelocity(0.0)
right_motor.setVelocity(0.0)

# Cap our command limit to the actual motor capability to avoid Webots warnings.
try:
    motor_limit = min(float(left_motor.getMaxVelocity()), float(right_motor.getMaxVelocity()))
    WHEEL_CMD_LIMIT = min(WHEEL_CMD_LIMIT, motor_limit)
except Exception:
    pass

left_cam = robot.getDevice("left_camera")
right_cam = robot.getDevice("right_camera")
left_cam.enable(timestep)
right_cam.enable(timestep)

try:
    camera_display = robot.getDevice("camera_display")
except Exception:
    camera_display = None

# If this node is not the configured car, keep it idle so only car_1 moves.
if my_cfg is None:
    while robot.step(timestep) != -1:
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
    raise SystemExit(0)

last_steering = 0.0
last_speed = 0.45
display_step = 0

while robot.step(timestep) != -1:
    try:
        # If a team controller is available, call it with HxWx3 images.
        need_images = control is not None or camera_display is not None
        if need_images:
            # Grab images from cameras and convert to H,W,3 uint8 arrays.
            left_raw = left_cam.getImage()
            left_arr = np.frombuffer(left_raw, dtype=np.uint8).reshape((IMG_H, IMG_W, 4))[:, :, :3].copy()
            right_raw = right_cam.getImage()
            right_arr = np.frombuffer(right_raw, dtype=np.uint8).reshape((IMG_H, IMG_W, 4))[:, :, :3].copy()

            if camera_display is not None and display_step % DISPLAY_UPDATE_STEPS == 0:
                _render_camera_pair(camera_display, left_arr, right_arr)
            display_step += 1

        if control is not None:

            # Call the student's control function. It should return (steering, speed_norm).
            try:
                steering, speed = control(left_arr, right_arr, robot.getTime())
                steering = float(np.clip(steering, -1.0, 1.0))
                speed = float(max(0.0, min(1.0, speed)))
            except Exception:
                # If the team controller errors, fall back to safe reduced values.
                steering = last_steering * 0.6
                speed = last_speed * 0.6
        else:
            # Fallback: simple lane-following heuristic using left camera.
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



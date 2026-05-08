"""OpenCV-based controller used as sdk/my_controller.py.

This implementation mirrors the tutorial example in
`sdk/examples/team_controller_tutorial.py` and provides a simple,
efficient lane follower + obstacle avoidance using `cv2`.
"""

from __future__ import annotations

try:
    import cv2
    HAVE_CV2 = True
except Exception:
    cv2 = None
    HAVE_CV2 = False

import numpy as np

# Image params
IMG_H, IMG_W = 480, 640
ROI_TOP = int(IMG_H * 0.55)
ROI_BOT = int(IMG_H * 0.95)

# Controller params
KP, KI, KD = 1.2, 0.0, 0.35
BASE_SPEED = 0.6
MIN_SPEED = 0.5
SPEED_TURN_PENALTY = 1.0
STEER_CLAMP = 1.0

# Obstacle detection
OBS_S_MIN = 0.35
OBS_V_MIN = 40
OBS_MIN_PIXELS = 180
OBS_EMERGENCY = 2500
OBS_AVOID_GAIN = 0.9

# LPF
STEER_ALPHA = 0.65

_state = {"prev_error": 0.0, "integral": 0.0, "prev_t": None, "steer_lpf": 0.0}


def _estimate_lane_center_cv(bgr: np.ndarray) -> float | None:
    roi = bgr[ROI_TOP:ROI_BOT]
    if HAVE_CV2:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, th = cv2.threshold(blur, 90, 255, cv2.THRESH_BINARY_INV)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        m = cv2.moments(th)
        if m["m00"] < 50:
            return None
        cx = m["m10"] / m["m00"]
        return float(cx)
    else:
        gray = roi.mean(axis=2)
        th = gray < 90
        col_hits = th.sum(axis=0)
        if col_hits.sum() < 50:
            return None
        xs = np.arange(IMG_W)
        cx = float((xs * col_hits).sum() / col_hits.sum())
        return cx


def _detect_obstacle_cv(bgr: np.ndarray) -> tuple[int, float] | None:
    roi = bgr[int(IMG_H * 0.4):int(IMG_H * 0.9)]
    if HAVE_CV2:
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        s = s.astype(np.float32) / 255.0
        v = v.astype(np.float32)
        mask = (s > OBS_S_MIN) & (v > OBS_V_MIN)
    else:
        arr = roi.astype(np.float32)
        v = arr.max(axis=2)
        mn = arr.min(axis=2)
        sat = np.where(v > 1e-3, (v - mn) / np.maximum(v, 1e-3), 0.0)
        mask = (sat > OBS_S_MIN) & (v > OBS_V_MIN)
    cnt = int(mask.sum())
    if cnt < OBS_MIN_PIXELS:
        return None
    cols = mask.sum(axis=0)
    if cols.sum() == 0:
        return None
    xs = np.arange(IMG_W)
    cx = float((xs * cols).sum() / cols.sum())
    cx_norm = (cx - IMG_W / 2) / (IMG_W / 2)
    return cnt, cx_norm


def control(left_img: np.ndarray, right_img: np.ndarray, timestamp: float) -> tuple[float, float]:
    cx = _estimate_lane_center_cv(left_img)
    if cx is None:
        return 0.0, 0.15

    lane_error = (cx - IMG_W / 2) / (IMG_W / 2)
    obs = _detect_obstacle_cv(left_img)
    error = lane_error
    emergency = False
    if obs is not None:
        cnt, obs_x = obs
        centrality = max(0.0, 1.0 - abs(obs_x))
        avoid_dir = -np.sign(obs_x) if abs(obs_x) > 0.05 else 1.0
        proximity = min(1.0, cnt / 2000.0)
        offset = OBS_AVOID_GAIN * avoid_dir * centrality * proximity
        error = float(np.clip(lane_error + offset, -1.5, 1.5))
        if cnt >= OBS_EMERGENCY:
            emergency = True

    prev_t = _state["prev_t"]
    dt = 0.032 if prev_t is None else max(1e-3, timestamp - prev_t)
    derivative = (error - _state["prev_error"]) / dt
    derivative = float(np.clip(derivative, -8.0, 8.0))
    _state["integral"] += error * dt
    _state["integral"] = float(np.clip(_state["integral"], -1.0, 1.0))

    steering_raw = KP * error + KI * _state["integral"] + KD * derivative
    if emergency:
        steering_raw = -np.sign(obs_x) * STEER_CLAMP if abs(obs_x) > 0.02 else STEER_CLAMP

    steer_lpf = STEER_ALPHA * steering_raw + (1 - STEER_ALPHA) * _state["steer_lpf"]
    steering = float(np.clip(steer_lpf, -STEER_CLAMP, STEER_CLAMP))

    if emergency:
        speed = 0.18
    else:
        speed = BASE_SPEED * (1.0 - SPEED_TURN_PENALTY * abs(steering))
        speed = float(np.clip(speed, MIN_SPEED, 1.0))

    _state["prev_error"] = error
    _state["prev_t"] = timestamp
    _state["steer_lpf"] = steering

    return steering, speed


if __name__ == "__main__":
    # simple smoke tests
    blank = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    print("blank ->", control(blank, blank, 0.0))
    img = np.full((IMG_H, IMG_W, 3), 200, dtype=np.uint8)
    img[:, 120:200, :] = 20
    print("left lane ->", control(img, img, 0.032))
    img = np.full((IMG_H, IMG_W, 3), 130, dtype=np.uint8)
    img[:, 300:340, :] = 20
    img[200:360, 280:360, 0] = 255
    img[200:360, 280:360, 1] = 200
    img[200:360, 280:360, 2] = 0
    print("center lane + obs ->", control(img, img, 0.032))
    _reset_state()
    img = np.full((IMG_H, IMG_W, 3), 130, dtype=np.uint8)
    img[:, 300:340, :] = 20
    img[200:360, 80:180, 0] = 255
    img[200:360, 80:180, 1] = 200
    img[200:360, 80:180, 2] = 0
    s, v = control(img, img, 0.032)
    print(f"lane-center + obs-L   → steering={s:+.3f} speed={v:.3f}   (应为正，向右避)")

    # 6) 障碍偏右：应向左避让
    _reset_state()
    img = np.full((IMG_H, IMG_W, 3), 130, dtype=np.uint8)
    img[:, 300:340, :] = 20
    img[200:360, 460:560, 0] = 255
    img[200:360, 460:560, 1] = 200
    img[200:360, 460:560, 2] = 0
    s, v = control(img, img, 0.032)
    print(f"lane-center + obs-R   → steering={s:+.3f} speed={v:.3f}   (应为负，向左避)")

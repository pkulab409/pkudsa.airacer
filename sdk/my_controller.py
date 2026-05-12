"""TeslaModel3 controller: stereo cameras + OpenCV lane detection.

This controller reads left/right cameras named "left_camera" and "right_camera",
performs a simple lane detection using OpenCV, and outputs steering, speed, and
turn-signal decisions. It is designed for the TeslaModel3 node in Webots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, List

import math
import pathlib
import re

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
MAX_STEER_ANGLE = 0.85
SIGNAL_THRESHOLD = 0.25
FULL_CONFIDENCE_LINE_COUNT = 8.0
MIN_EDGE_DENSITY = 0.003
GRAY_CHANGE_THRESHOLD = 1.5
STRAIGHT_DEADBAND = 0.02
OFFSET_SMOOTHING = 0.7
STEER_SMOOTHING = 0.6
MIN_CONFIDENCE = 0.15
MAP_HEADING_GAIN = 1.2
MAP_CTE_GAIN = 0.6
MAP_BLEND_MIN = 0.2
MAP_BLEND_MAX = 0.6
TRACK_WIDTH = 10.0
CURVE_LOOKAHEAD = 20
CURVE_SPEED_GAIN = 0.7


@dataclass
class VisionState:
    prev_left_gray: Optional[np.ndarray] = None
    prev_right_gray: Optional[np.ndarray] = None
    filtered_offset: float = 0.0
    filtered_conf: float = 0.0
    last_steering: float = 0.0
    prev_position: Optional[Tuple[float, float]] = None
    heading: Optional[float] = None


@dataclass
class TrackSegment:
    start: Tuple[float, float]
    end: Tuple[float, float]


@dataclass
class TrackCenterline:
    points: List[Tuple[float, float]]
    segments: List[TrackSegment]


@dataclass
class ControlDecision:
    steering: float
    speed: float
    signal: str  # "left", "right", "off"


def camera_to_bgr(camera) -> Optional[np.ndarray]:
    width = camera.getWidth()
    height = camera.getHeight()
    image = camera.getImage()
    if image is None:
        return None
    buffer = np.frombuffer(image, np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(buffer, cv2.COLOR_BGRA2BGR)


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
    y_top = int(height * 0.65)

    def line_x(slope: float, intercept: float, y: int) -> int:
        return int((y - intercept) / slope)

    left_x_bottom = line_x(left[0], left[1], y_bottom)
    right_x_bottom = line_x(right[0], right[1], y_bottom)
    lane_center = (left_x_bottom + right_x_bottom) / 2.0
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


def combine_offsets(left_offset: float, left_conf: float, right_offset: float, right_conf: float) -> float:
    total = left_conf + right_conf
    if total <= 0.0:
        return 0.0
    return float((left_offset * left_conf + right_offset * right_conf) / total)


def clamp(value: float, min_v: float, max_v: float) -> float:
    return float(max(min_v, min(max_v, value)))


def normalize_angle(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _append_point(points: List[Tuple[float, float]], point: Tuple[float, float]) -> None:
    if not points:
        points.append(point)
        return
    last = points[-1]
    if math.hypot(point[0] - last[0], point[1] - last[1]) > 1e-3:
        points.append(point)


def _sample_line(points: List[Tuple[float, float]], start: Tuple[float, float], end: Tuple[float, float], steps: int) -> None:
    for i in range(steps + 1):
        t = i / max(steps, 1)
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        _append_point(points, (x, y))


def _rotation_angle(line: str) -> Optional[float]:
    parts = line.strip().split()
    if len(parts) == 5 and parts[0] == "rotation" and parts[1] == "0" and parts[2] == "0" and parts[3] == "1":
        try:
            return float(parts[4])
        except ValueError:
            return None
    return None


def _parse_waypoints(buffer: List[float]) -> List[Tuple[float, float]]:
    points = []
    for i in range(0, len(buffer), 3):
        if i + 1 < len(buffer):
            points.append((buffer[i], buffer[i + 1]))
    return points


def build_segments(points: List[Tuple[float, float]]) -> List[TrackSegment]:
    if len(points) < 2:
        return []
    return [TrackSegment(start=points[i], end=points[i + 1]) for i in range(len(points) - 1)]


def load_track_centerline() -> TrackCenterline:
    worlds_dir = pathlib.Path(__file__).resolve().parents[1] / "worlds"
    wbt_path = worlds_dir / "track_basic.wbt"
    if not wbt_path.exists():
        return TrackCenterline(points=[], segments=[])

    points: List[Tuple[float, float]] = []
    translations = {}
    last_translation: Optional[Tuple[float, float]] = None
    name_pattern = re.compile(r"name\s+\"checkpoint_(\d+)\"")

    state: Optional[str] = None
    depth = 0
    translation: Optional[Tuple[float, float]] = None
    rotation: float = 0.0
    radius: Optional[float] = None
    waypoints: List[float] = []
    in_waypoints = False

    with wbt_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if line.startswith("Road {"):
                state = "road"
                depth = 1
                translation = None
                rotation = 0.0
                waypoints = []
                in_waypoints = False
            elif line.startswith("CurvedRoadSegment {"):
                state = "curve"
                depth = 1
                translation = None
                rotation = 0.0
                radius = None
                in_waypoints = False
            elif state is not None:
                depth += line.count("{")
                depth -= line.count("}")

            if line.startswith("translation "):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        last_translation = (float(parts[1]), float(parts[2]))
                        if state in {"road", "curve"}:
                            translation = last_translation
                    except ValueError:
                        last_translation = None

            angle = _rotation_angle(line)
            if angle is not None and state in {"road", "curve"}:
                rotation = angle

            if state == "curve" and line.startswith("curvatureRadius"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        radius = float(parts[1])
                    except ValueError:
                        radius = None

            if state == "road" and line.startswith("wayPoints"):
                in_waypoints = True
                waypoints = []
                continue

            if in_waypoints:
                if "]" in line:
                    in_waypoints = False
                numbers = re.findall(r"-?\d+\.?\d*", line)
                for num in numbers:
                    waypoints.append(float(num))

            match = name_pattern.search(line)
            if match and last_translation is not None:
                translations[int(match.group(1))] = last_translation
                last_translation = None

            if state is not None and depth == 0:
                if state == "road" and translation and waypoints:
                    local_points = _parse_waypoints(waypoints)
                    cos_r = math.cos(rotation)
                    sin_r = math.sin(rotation)
                    for idx in range(len(local_points) - 1):
                        start = local_points[idx]
                        end = local_points[idx + 1]
                        sx = start[0] * cos_r - start[1] * sin_r + translation[0]
                        sy = start[0] * sin_r + start[1] * cos_r + translation[1]
                        ex = end[0] * cos_r - end[1] * sin_r + translation[0]
                        ey = end[0] * sin_r + end[1] * cos_r + translation[1]
                        _sample_line(points, (sx, sy), (ex, ey), 6)
                elif state == "curve" and translation and radius:
                    # Approximate quarter-circle arc using rotation as start angle.
                    start_angle = rotation
                    end_angle = rotation + math.pi / 2.0
                    steps = 10
                    for i in range(steps + 1):
                        t = i / steps
                        angle_val = start_angle + (end_angle - start_angle) * t
                        x = translation[0] + radius * math.cos(angle_val)
                        y = translation[1] + radius * math.sin(angle_val)
                        _append_point(points, (x, y))
                state = None
                depth = 0
                translation = None
                rotation = 0.0
                radius = None
                waypoints = []
                in_waypoints = False

    if len(points) < 2 and translations:
        checkpoints = [translations[k] for k in sorted(translations.keys())]
        for idx in range(len(checkpoints)):
            _sample_line(points, checkpoints[idx], checkpoints[(idx + 1) % len(checkpoints)], 8)

    return TrackCenterline(points=points, segments=build_segments(points))


def closest_segment(position: Tuple[float, float], segments: List[TrackSegment]) -> Optional[TrackSegment]:
    if not segments:
        return None
    px, py = position
    best_seg = None
    best_dist = None
    for seg in segments:
        sx, sy = seg.start
        ex, ey = seg.end
        vx, vy = ex - sx, ey - sy
        wx, wy = px - sx, py - sy
        seg_len2 = vx * vx + vy * vy
        if seg_len2 <= 1e-6:
            continue
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg_len2))
        proj_x = sx + t * vx
        proj_y = sy + t * vy
        dx = px - proj_x
        dy = py - proj_y
        dist = dx * dx + dy * dy
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_seg = seg
    return best_seg


def closest_point_index(position: Tuple[float, float], points: List[Tuple[float, float]]) -> Optional[int]:
    if not points:
        return None
    px, py = position
    best_idx = None
    best_dist = None
    for idx, (x, y) in enumerate(points):
        dist = (px - x) ** 2 + (py - y) ** 2
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_idx = idx
    return best_idx


def curvature_ahead(points: List[Tuple[float, float]], start_idx: int, lookahead: int) -> float:
    if len(points) < 3:
        return 0.0
    end_idx = min(len(points) - 2, start_idx + lookahead)
    max_turn = 0.0
    for idx in range(start_idx, end_idx):
        x1, y1 = points[idx]
        x2, y2 = points[idx + 1]
        x3, y3 = points[idx + 2]
        h1 = math.atan2(y2 - y1, x2 - x1)
        h2 = math.atan2(y3 - y2, x3 - x2)
        turn = abs(normalize_angle(h2 - h1))
        if turn > max_turn:
            max_turn = turn
    return max_turn


def heading_from_compass(compass_values) -> Optional[float]:
    if compass_values is None:
        return None
    x, _, z = compass_values
    return math.atan2(x, z)


def heading_from_position(prev_pos: Optional[Tuple[float, float]],
                          curr_pos: Tuple[float, float]) -> Optional[float]:
    if prev_pos is None:
        return None
    dx = curr_pos[0] - prev_pos[0]
    dy = curr_pos[1] - prev_pos[1]
    if abs(dx) < 1e-4 and abs(dy) < 1e-4:
        return None
    return math.atan2(dy, dx)


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
    track_segments: List[TrackSegment],
    track_points: List[Tuple[float, float]],
    position: Optional[Tuple[float, float]],
    heading: Optional[float],
) -> ControlDecision:
    left_offset, left_conf = lane_center_offset(left_frame)
    right_offset, right_conf = lane_center_offset(right_frame)

    left_change = grayscale_change(state.prev_left_gray, left_frame)
    right_change = grayscale_change(state.prev_right_gray, right_frame)
    change_metric = max(left_change, right_change)

    left_valid = left_conf > 0.0
    right_valid = right_conf > 0.0
    if left_valid and right_valid:
        offset = combine_offsets(left_offset, left_conf, right_offset, right_conf)
        lane_conf = clamp(max(left_conf, right_conf), 0.0, 1.0)
    elif left_valid:
        offset = left_offset
        lane_conf = clamp(left_conf, 0.0, 1.0)
    elif right_valid:
        offset = right_offset
        lane_conf = clamp(right_conf, 0.0, 1.0)
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
    map_steer: Optional[float] = None
    if position is not None and heading is not None:
        seg = closest_segment(position, track_segments)
        if seg is not None:
            sx, sy = seg.start
            ex, ey = seg.end
            seg_heading = math.atan2(ey - sy, ex - sx)
            heading_error = normalize_angle(seg_heading - heading)
            vx, vy = ex - sx, ey - sy
            px, py = position
            wx, wy = px - sx, py - sy
            seg_len = math.hypot(vx, vy)
            if seg_len > 1e-6:
                cross = vx * wy - vy * wx
                cte = cross / seg_len
                cte_norm = clamp(cte / (TRACK_WIDTH * 0.5), -1.0, 1.0)
                map_steer = clamp(
                    heading_error * MAP_HEADING_GAIN + cte_norm * MAP_CTE_GAIN,
                    -1.0,
                    1.0,
                )

    if map_steer is not None:
        blend = clamp(MAP_BLEND_MIN + (1.0 - lane_conf) * MAP_BLEND_MAX, 0.0, 0.85)
        steering = steering * (1.0 - blend) + map_steer * blend

    speed = decide_speed(steering, lane_conf)
    if position is not None and track_points:
        idx = closest_point_index(position, track_points)
        if idx is not None:
            turn = curvature_ahead(track_points, idx, CURVE_LOOKAHEAD)
            norm_turn = clamp(turn / (math.pi / 2.0), 0.0, 1.0)
            curve_speed = MAX_SPEED * (1.0 - CURVE_SPEED_GAIN * norm_turn)
            curve_speed = clamp(curve_speed, MIN_SPEED, MAX_SPEED)
            speed = min(speed, curve_speed)
    signal = decide_turn_signal(steering)
    return ControlDecision(steering=steering, speed=speed, signal=signal)


# ---------------------------------------------------------------------------
# Module-level state for the sandbox control() interface
# ---------------------------------------------------------------------------
_vision_state = VisionState()
_track_centerline: Optional[TrackCenterline] = None


def _get_track_centerline() -> TrackCenterline:
    global _track_centerline
    if _track_centerline is None:
        _track_centerline = load_track_centerline()
    return _track_centerline


def control(
    left_img: np.ndarray,   # (480, 640, 3), uint8, BGR
    right_img: np.ndarray,  # (480, 640, 3), uint8, BGR
    timestamp: float,       # seconds
) -> tuple[float, float]:
    """Sandbox entry point called every frame by the race platform.

    Returns
    -------
    steering : float  in [-1, 1]  negative = left, positive = right
    speed    : float  in [0,  1]  normalised throttle
    """
    tc = _get_track_centerline()

    left_frame: Optional[np.ndarray] = left_img if left_img is not None else None
    right_frame: Optional[np.ndarray] = right_img if right_img is not None else None

    # Discard right frame if it has no useful lane features
    if right_frame is not None and not frame_has_lane_features(right_frame):
        right_frame = None

    decision = compute_control(
        left_frame,
        right_frame,
        _vision_state,
        tc.segments,
        tc.points,
        position=None,
        heading=None,
    )

    # Update grayscale history for motion detection on next frame
    if left_frame is not None:
        _vision_state.prev_left_gray = cv2.cvtColor(left_frame, cv2.COLOR_BGR2GRAY)
    if right_frame is not None:
        _vision_state.prev_right_gray = cv2.cvtColor(right_frame, cv2.COLOR_BGR2GRAY)

    # Normalise speed from [MIN_SPEED, MAX_SPEED] to [0, 1]
    speed_norm = clamp((decision.speed - MIN_SPEED) / (MAX_SPEED - MIN_SPEED), 0.0, 1.0)
    steering = clamp(decision.steering, -1.0, 1.0)

    return steering, speed_norm
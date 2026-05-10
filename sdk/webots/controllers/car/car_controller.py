from controller import Robot
import cv2
import numpy as np
import os
import json


BASE_SPEED = 24000
MIN_SPEED = 12000
MAX_SPEED = 38000
STEER_GAIN = 60000.0
FLOW_GAIN = 0.2
FULL_CONFIDENCE_LINE_COUNT = 0.6
CONF_SPEED_BOOST = 0.5
CONF_STEER_BOOST = 0.35
MAX_STEER_ANGLE = 1.04
LEFT_CAMERA_NAMES = "left_camera"
RIGHT_CAMERA_NAMES = "right_camera"


def get_camera(robot, name):
    """Return (device, name) if present, else (None, None)."""
    try:
        dev = robot.getDevice(name)
        return (dev, name) if dev is not None else (None, None)
    except Exception:
        return (None, None)


def camera_to_bgr(camera):
    width = camera.getWidth()
    height = camera.getHeight()
    image = camera.getImage()
    if image is None:
        return None
    buffer = np.frombuffer(image, np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(buffer, cv2.COLOR_BGRA2BGR)


def region_of_interest(edges):
    height, width = edges.shape
    mask = np.zeros_like(edges)
    polygon = np.array([
        [0, height],
        [width, height],
        [int(width * 0.6), int(height * 0.55)],
        [int(width * 0.4), int(height * 0.55)],
    ], np.int32)
    cv2.fillPoly(mask, [polygon], 255)
    return cv2.bitwise_and(edges, mask)


def average_lane_line(lines, width, height):
    if lines is None:
        return None
    left_lines = []
    right_lines = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if x2 == x1:
            continue
        slope = (y2 - y1) / (x2 - x1)
        if abs(slope) < 0.5:
            continue
        intercept = y1 - slope * x1
        if slope < 0:
            left_lines.append((slope, intercept))
        else:
            right_lines.append((slope, intercept))
    left = np.mean(left_lines, axis=0) if left_lines else None
    right = np.mean(right_lines, axis=0) if right_lines else None
    return left, right


def lane_center_offset(frame):
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    roi = region_of_interest(edges)
    lines = cv2.HoughLinesP(roi, 2, np.pi / 180, 50, minLineLength=40, maxLineGap=100)
    line_count = 0 if lines is None else len(lines)
    lanes = average_lane_line(lines, width, height)
    if lanes is None:
        return 0.0, 0.0
    left, right = lanes
    if left is None or right is None:
        return 0.0, 0.0
    y_bottom = height
    y_top = int(height * 0.6)

    def line_x(slope, intercept, y):
        return int((y - intercept) / slope)

    if left is None or right is None:
        return 0.0, 0.0

    left_x_bottom = line_x(left[0], left[1], y_bottom)
    right_x_bottom = line_x(right[0], right[1], y_bottom)
    lane_center = (left_x_bottom + right_x_bottom) / 2.0
    image_center = width / 2.0
    offset = (lane_center - image_center) / image_center
    confidence = min(1.0, line_count / FULL_CONFIDENCE_LINE_COUNT)
    return float(offset), float(confidence)


def combine_offsets(left_offset, left_conf, right_offset, right_conf):
    total = left_conf + right_conf
    if total <= 0.0:
        return 0.0
    return float((left_offset * left_conf + right_offset * right_conf) / total)


def frame_to_gray(frame):
    if frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def offset_and_confidence(frame):
    if frame is None:
        return 0.0, 0.0
    return lane_center_offset(frame)


def combine_speeds(*speeds):
    valid = [speed for speed in speeds if speed is not None]
    if not valid:
        return BASE_SPEED
    return float(np.mean(valid))


def estimate_speed(prev_gray, gray):
    if prev_gray is None or gray is None:
        return BASE_SPEED
    flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    roi = mag[int(mag.shape[0] * 0.5):, :]
    mean_mag = float(np.mean(roi))
    target_speed = BASE_SPEED - FLOW_GAIN * mean_mag
    return float(np.clip(target_speed, MIN_SPEED, MAX_SPEED))


def speed_from_frames(prev_gray, gray):
    if prev_gray is None or gray is None:
        return None
    return estimate_speed(prev_gray, gray)


def run():
    # Use the generic Robot API and emulate a Driver by controlling left/right
    # wheel motors (differential drive). This avoids using the Webots `vehicle`
    # library which requires a node based on the `Car` node.
    robot = Robot()
    timestep = int(robot.getBasicTimeStep())

    # Read race config and determine whether this controller instance is
    # assigned to a car in the config. If not assigned, idle and exit. This
    # prevents the same controller script from actively controlling every car
    # node in the world.
    config_path = os.environ.get('RACE_CONFIG_PATH', 'race_config.json')
    try:
        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)
    except Exception:
        config = {"cars": []}

    my_node_id = robot.getName()
    my_config = next((c for c in config.get('cars', []) if c.get('car_slot') == my_node_id), None)
    if my_config is None:
        # Not assigned: idle until simulation ends and exit cleanly.
        while robot.step(timestep) != -1:
            pass
        raise SystemExit(0)

    left_camera, left_name = get_camera(robot, LEFT_CAMERA_NAMES)
    right_camera, right_name = get_camera(robot, RIGHT_CAMERA_NAMES)

    if left_camera is None and right_camera is None:
        raise RuntimeError("No cameras found for controller.")

    same_camera_instance = (
        left_name is not None and right_name is not None and left_name == right_name
    )
    if same_camera_instance:
        right_camera = None

    if left_camera is not None:
        left_camera.enable(timestep)
    if right_camera is not None:
        right_camera.enable(timestep)

    # Motors (differential drive + optional front drive/steer)
    try:
        left_motor = robot.getDevice('left_motor')
        right_motor = robot.getDevice('right_motor')
        fl_motor = robot.getDevice('fl_motor')
        fr_motor = robot.getDevice('fr_motor')
        fl_steer = robot.getDevice('fl_steer')
        fr_steer = robot.getDevice('fr_steer')
        left_motor.setPosition(float('inf'))
        right_motor.setPosition(float('inf'))
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
        for motor in (fl_motor, fr_motor):
            if motor is not None:
                motor.setPosition(float('inf'))
                motor.setVelocity(0.0)
        for steer in (fl_steer, fr_steer):
            if steer is not None:
                steer.setVelocity(2.0)
    except Exception:
        # If motors are not present, continue but setting speed will be a no-op
        left_motor = right_motor = None
        fl_motor = fr_motor = None
        fl_steer = fr_steer = None

    WHEEL_MAX = 8000.0

    def set_velocity(norm_speed, steering):
        # norm_speed: 0..1, steering: -1..1
        if left_motor is None or right_motor is None:
            return
        v = norm_speed * WHEEL_MAX
        diff = steering * WHEEL_MAX * 0.5
        v_l = max(-WHEEL_MAX, min(WHEEL_MAX, v + diff))
        v_r = max(-WHEEL_MAX, min(WHEEL_MAX, v - diff))
        left_motor.setVelocity(v_l)
        right_motor.setVelocity(v_r)
        if fl_motor is not None:
            fl_motor.setVelocity(v_l)
        if fr_motor is not None:
            fr_motor.setVelocity(v_r)

    def stop_motors():
        if left_motor is None or right_motor is None:
            return
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
        if fl_motor is not None:
            fl_motor.setVelocity(0.0)
        if fr_motor is not None:
            fr_motor.setVelocity(0.0)

    prev_left_gray = None
    prev_right_gray = None

    while robot.step(timestep) != -1:
        left_frame = camera_to_bgr(left_camera) if left_camera is not None else None
        right_frame = camera_to_bgr(right_camera) if right_camera is not None else None
        if left_frame is None and right_frame is None:
            continue

        left_gray = frame_to_gray(left_frame)
        right_gray = frame_to_gray(right_frame)

        left_offset, left_conf = offset_and_confidence(left_frame)
        right_offset, right_conf = offset_and_confidence(right_frame)
        offset = combine_offsets(left_offset, left_conf, right_offset, right_conf)
        lane_conf = float(np.clip(max(left_conf, right_conf), 0.0, 1.0))

        steering = float(np.clip(-offset * STEER_GAIN, -1.0, 1.0))
        steering = float(np.clip(steering * (1.0 + CONF_STEER_BOOST * lane_conf), -1.0, 1.0))
        steer_angle = float(np.clip(steering * MAX_STEER_ANGLE, -MAX_STEER_ANGLE, MAX_STEER_ANGLE))
        if fl_steer is not None:
            fl_steer.setPosition(steer_angle)
        if fr_steer is not None:
            fr_steer.setPosition(steer_angle)

        left_speed = speed_from_frames(prev_left_gray, left_gray)
        right_speed = speed_from_frames(prev_right_gray, right_gray)
        target_speed = combine_speeds(left_speed, right_speed)
        boosted_speed = BASE_SPEED + (MAX_SPEED - BASE_SPEED) * (CONF_SPEED_BOOST * lane_conf)
        target_speed = max(target_speed, boosted_speed)

        # Convert the original speed (rough absolute estimate) to a normalized
        # 0..1 value for differential wheel velocity control.
        norm_speed = float(np.clip(target_speed / MAX_SPEED, 0.0, 1.0))

        set_velocity(norm_speed, steering)

        if left_gray is not None:
            prev_left_gray = left_gray
        if right_gray is not None:
            prev_right_gray = right_gray


run()
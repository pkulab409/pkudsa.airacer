"""
Webots car controller for AI Racer platform.
Supports both vehicle.Driver API (TeslaModel3-based cars) and basic Robot API.
Launches student code in a sandboxed subprocess, exchanges camera frames via
stdin/stdout, and applies the returned steering/speed commands.

Pattern based on sdk/webots/controllers/car/car_controller.py.
"""

from __future__ import annotations

import os
import json
import sys
import struct
import subprocess
import threading
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Driver vs Robot detection (same pattern as SDK)
# ---------------------------------------------------------------------------

try:
    from vehicle import Driver  # type: ignore
    _USE_DRIVER = True
except Exception:
    from controller import Robot  # type: ignore
    _USE_DRIVER = False


def get_device(robot, names):
    """Try multiple device names (same helper as SDK)."""
    for name in names:
        try:
            dev = robot.getDevice(name)
        except Exception:
            dev = None
        if dev is not None:
            return dev
    return None


def clamp(value: float, min_v: float, max_v: float) -> float:
    return float(max(min_v, min(max_v, value)))


# ---------------------------------------------------------------------------
# Camera helpers (same as SDK)
# ---------------------------------------------------------------------------

def camera_to_bgr(camera) -> Optional[np.ndarray]:
    if camera is None:
        return None
    image = camera.getImage()
    if image is None:
        return None
    w = camera.getWidth()
    h = camera.getHeight()
    buffer = np.frombuffer(image, np.uint8).reshape((h, w, 4))
    return buffer[:, :, :3].copy()


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

def run() -> None:
    # --- Init robot/driver (same as SDK) ---
    if _USE_DRIVER:
        driver = Driver()
        robot = driver
        use_driver = True
    else:
        driver = Robot()
        robot = driver
        use_driver = False

    timestep = int(robot.getBasicTimeStep())

    # --- Check if this car is configured in race_config (same as SDK) ---
    config_path = os.environ.get('RACE_CONFIG_PATH', 'race_config.json')
    if config_path:
        try:
            with open(config_path, encoding='utf-8') as f:
                cfg = json.load(f)
            my_node = robot.getName()
            my_config = next(
                (c for c in cfg.get('cars', []) if c.get('car_slot') == my_node), None
            )
            if my_config is None:
                while (driver.step() if use_driver else robot.step(timestep)) != -1:
                    pass
                return
            team_id = my_config['team_id']
            code_path = my_config['code_path']
        except Exception:
            team_id = 'local_team'
            code_path = ''
    else:
        team_id = 'local_team'
        code_path = ''

    # --- Cameras (same as SDK) ---
    left_cam = get_device(robot, ['left_camera'])
    right_cam = get_device(robot, ['right_camera'])

    if left_cam is not None:
        left_cam.enable(timestep)
    if right_cam is not None:
        right_cam.enable(timestep)

    # -----------------------------------------------------------------------
    # Sandbox pipeline (simnode-specific)
    # -----------------------------------------------------------------------

    controller_dir = os.path.dirname(os.path.abspath(__file__))
    sandbox_script = os.path.join(controller_dir, 'sandbox_runner.py')

    _conda_prefix = os.environ.get('CONDA_PREFIX', '')
    _conda_python = ''
    if _conda_prefix:
        if sys.platform.startswith('win'):
            _conda_python = os.path.join(_conda_prefix, 'python.exe')
        else:
            _conda_python = os.path.join(_conda_prefix, 'bin', 'python')
    SANDBOX_PYTHON = (
        _conda_python if (_conda_python and os.path.isfile(_conda_python))
        else sys.executable
    )

    def launch_sandbox():
        kwargs = {}
        if sys.platform.startswith('win'):
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        return subprocess.Popen(
            [SANDBOX_PYTHON, sandbox_script, '--team-id', team_id, '--code-path', code_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **kwargs,
        )

    def drain_pipe(pipe, prefix):
        try:
            for line in iter(pipe.readline, b''):
                try:
                    sys.stderr.write(f'[{prefix}] {line.decode(errors="replace")}')
                    sys.stderr.flush()
                except Exception:
                    pass
        except Exception:
            pass

    def send_frame(proc, lbgr, rbgr, ts):
        lb = lbgr.tobytes() if lbgr is not None else b''
        rb = rbgr.tobytes() if rbgr is not None else b''
        msg = (struct.pack('<I', len(lb)) + lb +
               struct.pack('<I', len(rb)) + rb +
               struct.pack('<d', ts))
        proc.stdin.write(msg)
        proc.stdin.flush()

    def read_line_timeout(pipe, timeout=0.020):
        result: list[bytes] = [b'']
        def _reader():
            try:
                result[0] = pipe.readline()
            except Exception:
                result[0] = b''
        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout)
        return result[0]

    # -----------------------------------------------------------------------
    # Motors (same pattern as SDK: Driver API or differential drive)
    # -----------------------------------------------------------------------
    MAX_STEER_ANGLE = 0.85
    MAX_SPEED_KMH = 22.0
    WHEEL_MAX = 10.0

    left_motor = right_motor = None

    if not use_driver:
        left_motor = get_device(robot, ['left_motor'])
        right_motor = get_device(robot, ['right_motor'])
        if left_motor is not None:
            left_motor.setPosition(float('inf'))
            left_motor.setVelocity(0.0)
        if right_motor is not None:
            right_motor.setPosition(float('inf'))
            right_motor.setVelocity(0.0)

    def set_velocity(speed_norm, steer_norm):
        if use_driver:
            driver.setCruisingSpeed(speed_norm * MAX_SPEED_KMH)
            driver.setSteeringAngle(steer_norm * MAX_STEER_ANGLE)
        else:
            v = speed_norm * WHEEL_MAX
            d = steer_norm * WHEEL_MAX * 0.5
            vl = clamp(v + d, -WHEEL_MAX, WHEEL_MAX)
            vr = clamp(v - d, -WHEEL_MAX, WHEEL_MAX)
            if left_motor is not None:
                left_motor.setVelocity(vl)
            if right_motor is not None:
                right_motor.setVelocity(vr)

    def stop_motors():
        if use_driver:
            driver.setCruisingSpeed(0.0)
            driver.setSteeringAngle(0.0)
        else:
            if left_motor is not None:
                left_motor.setVelocity(0.0)
            if right_motor is not None:
                right_motor.setVelocity(0.0)

    # -----------------------------------------------------------------------
    # Main loop state
    # -----------------------------------------------------------------------
    proc = launch_sandbox()
    stderr_thread = threading.Thread(
        target=drain_pipe, args=(proc.stderr, f'sandbox:{team_id}'), daemon=True,
    )
    stderr_thread.start()

    last_steering = 0.0
    last_speed = 0.5
    warn_count = 0
    force_stopped = False
    stop_until = 0.0
    disqualified = False
    restart_stop_until = 0.0

    # -----------------------------------------------------------------------
    # Main loop (same step() pattern as SDK)
    # -----------------------------------------------------------------------
    while (driver.step() if use_driver else robot.step(timestep)) != -1:
        current_time = robot.getTime()

        # IPC from supervisor
        custom_data = robot.getCustomData()
        if custom_data:
            try:
                cmd = json.loads(custom_data)
                if cmd.get('cmd') == 'stop' and not force_stopped:
                    stop_until = current_time + float(cmd.get('duration', 2.0))
                    force_stopped = True
                elif cmd.get('cmd') == 'disqualify':
                    disqualified = True
            except (json.JSONDecodeError, ValueError):
                pass

        if disqualified:
            stop_motors()
            continue

        if force_stopped:
            if current_time < stop_until:
                stop_motors()
                continue
            else:
                force_stopped = False

        if current_time < restart_stop_until:
            stop_motors()
            continue

        # Sandbox health
        if proc.poll() is not None:
            if proc.returncode == 2:
                disqualified = True
                stop_motors()
                continue
            else:
                restart_stop_until = current_time + 2.0
                proc = launch_sandbox()
                stderr_thread = threading.Thread(
                    target=drain_pipe, args=(proc.stderr, f'sandbox:{team_id}'), daemon=True,
                )
                stderr_thread.start()
                stop_motors()
                continue

        # Capture frames
        left_bgr = camera_to_bgr(left_cam)
        right_bgr = camera_to_bgr(right_cam)
        if left_bgr is None:
            left_bgr = np.zeros((480, 640, 3), dtype=np.uint8)
        if right_bgr is None:
            right_bgr = np.zeros((480, 640, 3), dtype=np.uint8)

        # Send to sandbox
        try:
            send_frame(proc, left_bgr, right_bgr, current_time)
        except Exception:
            set_velocity(last_speed, last_steering)
            continue

        # Read response
        raw = read_line_timeout(proc.stdout, 0.020)
        if raw is None or raw == b'':
            warn_count += 1
            steering = last_steering
            speed = last_speed
        else:
            try:
                out = json.loads(raw.decode().strip())
                steering = clamp(float(out['steering']), -1.0, 1.0)
                speed = clamp(max(0.0, float(out['speed'])), 0.0, 1.0)
                last_steering = steering
                last_speed = speed
                warn_count = 0
            except Exception:
                steering = last_steering
                speed = last_speed
                warn_count += 1

        if warn_count >= 3:
            warn_count = 0
            restart_stop_until = current_time + 5.0
            stop_motors()
            continue

        set_velocity(speed, steering)


if __name__ == '__main__':
    run()


"""
Webots car controller for AI Racer platform.
Uses the basic Robot API (differential drive) instead of the automotive Driver API.
Launches student code in a sandboxed subprocess, exchanges camera frames via
stdin/stdout, and applies the returned steering/speed commands to the motors.
"""

import os
import json
import sys
import struct
import subprocess
import threading

import numpy as np
from controller import Robot

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

robot    = Robot()
timestep = int(robot.getBasicTimeStep())

my_node_id  = robot.getName()
config_path = os.environ.get('RACE_CONFIG_PATH', 'race_config.json')
with open(config_path, encoding='utf-8') as f:
    config = json.load(f)

my_config = next((c for c in config['cars'] if c['car_slot'] == my_node_id), None)

if my_config is None:
    while robot.step(timestep) != -1:
        pass
    raise SystemExit(0)

team_id   = my_config['team_id']
code_path = my_config['code_path']

# ---------------------------------------------------------------------------
# Motors  (differential drive)
# ---------------------------------------------------------------------------

WHEEL_MAX = 10.0  # rad/s

left_motor  = robot.getDevice('left_motor')
right_motor = robot.getDevice('right_motor')
left_motor.setPosition(float('inf'))
right_motor.setPosition(float('inf'))
left_motor.setVelocity(0.0)
right_motor.setVelocity(0.0)

# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

IMG_H, IMG_W = 480, 640

left_cam  = robot.getDevice('left_camera')
right_cam = robot.getDevice('right_camera')
left_cam.enable(timestep)
right_cam.enable(timestep)

# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

controller_dir = os.path.dirname(os.path.abspath(__file__))
sandbox_script = os.path.join(controller_dir, 'sandbox_runner.py')

# Prefer the activated conda env's Python (has numpy/opencv) over Webots' bundled Python
_conda_prefix = os.environ.get('CONDA_PREFIX', '')

# Windows: <conda>\python.exe
# macOS/Linux: <conda>/bin/python
_conda_python = ''
if _conda_prefix:
    if sys.platform.startswith('win'):
        _conda_python = os.path.join(_conda_prefix, 'python.exe')
    else:
        _conda_python = os.path.join(_conda_prefix, 'bin', 'python')

SANDBOX_PYTHON = _conda_python if (_conda_python and os.path.isfile(_conda_python)) else sys.executable


def launch_sandbox():
    popen_kwargs = {}
    # Only available on Windows; prevents a console window from opening.
    if sys.platform.startswith('win'):
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    return subprocess.Popen(
        [SANDBOX_PYTHON, sandbox_script, '--team-id', team_id, '--code-path', code_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,
    )


def _drain_pipe_to_stderr(pipe, prefix: str):
    """Continuously drains a subprocess pipe to avoid deadlocks.

    If the child writes lots of logs to stderr and nobody reads it, the OS pipe
    buffer can fill up and block the child process. That can cascade into the
    controller appearing to "crash after running for a while".
    """
    try:
        for line in iter(pipe.readline, b''):
            try:
                sys.stderr.write(f"[{prefix}] {line.decode(errors='replace')}")
                sys.stderr.flush()
            except Exception:
                # Last resort: drop the line.
                pass
    except Exception:
        pass


def get_bgr(cam):
    raw = cam.getImage()
    arr = np.frombuffer(raw, dtype=np.uint8).reshape((IMG_H, IMG_W, 4))
    return arr[:, :, :3].copy()


def send_frame(proc, left_bgr, right_bgr, timestamp):
    left_b  = left_bgr.tobytes()
    right_b = right_bgr.tobytes()
    msg = (struct.pack('<I', len(left_b))  + left_b +
           struct.pack('<I', len(right_b)) + right_b +
           struct.pack('<d', timestamp))
    proc.stdin.write(msg)
    proc.stdin.flush()


def read_line_timeout(pipe, timeout=0.020):
    # bytes sentinel to keep typing and downstream logic simple
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


def set_velocity(speed, steering):
    """Convert normalised speed/steering to differential wheel velocities."""
    v    = speed * WHEEL_MAX
    diff = steering * WHEEL_MAX * 0.5
    v_l  = max(-WHEEL_MAX, min(WHEEL_MAX, v + diff))
    v_r  = max(-WHEEL_MAX, min(WHEEL_MAX, v - diff))
    left_motor.setVelocity(v_l)
    right_motor.setVelocity(v_r)


def stop_motors():
    left_motor.setVelocity(0.0)
    right_motor.setVelocity(0.0)


# ---------------------------------------------------------------------------
# Main loop state
# ---------------------------------------------------------------------------

proc               = launch_sandbox()
# Drain sandbox stderr so the child can't block on a full pipe.
_stderr_thread     = threading.Thread(
    target=_drain_pipe_to_stderr,
    args=(proc.stderr, f"sandbox:{team_id}"),
    daemon=True,
)
_stderr_thread.start()
last_steering      = 0.0
last_speed         = 0.5
warn_count         = 0
force_stopped      = False
stop_until         = 0.0
disqualified       = False
restart_stop_until = 0.0

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

while robot.step(timestep) != -1:
    current_time = robot.getTime()

    # --- Read IPC commands from Supervisor via customData ---
    custom_data = robot.getCustomData()
    if custom_data:
        try:
            cmd = json.loads(custom_data)
            if cmd.get('cmd') == 'stop' and not force_stopped:
                duration   = float(cmd.get('duration', 2.0))
                stop_until = current_time + duration
                force_stopped = True
            elif cmd.get('cmd') == 'disqualify':
                disqualified = True
        except (json.JSONDecodeError, ValueError):
            pass

    # --- Handle disqualified state ---
    if disqualified:
        stop_motors()
        continue

    # --- Handle stop penalty ---
    if force_stopped:
        if current_time < stop_until:
            stop_motors()
            continue
        else:
            force_stopped = False

    # --- Sandbox post-restart cooldown ---
    if current_time < restart_stop_until:
        stop_motors()
        continue

    # --- Check sandbox process health ---
    if proc.poll() is not None:
        exit_code = proc.returncode
        if exit_code == 2:
            disqualified = True
            stop_motors()
            continue
        else:
            restart_stop_until = current_time + 2.0
            proc = launch_sandbox()
            _stderr_thread = threading.Thread(
                target=_drain_pipe_to_stderr,
                args=(proc.stderr, f"sandbox:{team_id}"),
                daemon=True,
            )
            _stderr_thread.start()
            stop_motors()
            continue

    # --- Capture camera frames ---
    left_bgr  = get_bgr(left_cam)
    right_bgr = get_bgr(right_cam)

    # --- Send frame to sandbox ---
    try:
        send_frame(proc, left_bgr, right_bgr, current_time)
    except Exception:
        set_velocity(last_speed, last_steering)
        continue

    # --- Read response (20 ms timeout) ---
    raw = read_line_timeout(proc.stdout, 0.020)

    if raw is None or raw == b'':
        warn_count += 1
        steering = last_steering
        speed    = last_speed
    else:
        try:
            out      = json.loads(raw.decode().strip())
            steering = float(max(-1.0, min(1.0, out['steering'])))
            speed    = float(max(0.0,  min(1.0, out['speed'])))
            last_steering = steering
            last_speed    = speed
            warn_count    = 0
        except Exception:
            steering   = last_steering
            speed      = last_speed
            warn_count += 1

    # 3 consecutive timeouts → impose a 5-second stop penalty
    if warn_count >= 3:
        warn_count = 0
        restart_stop_until = current_time + 5.0
        stop_motors()
        continue

    set_velocity(speed, steering)

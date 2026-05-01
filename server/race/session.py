"""
Webots process lifecycle management.

Responsibilities:
- Write race_config.json before each race.
- Launch the Webots binary as a subprocess.
- Monitor the process in a background thread and invoke callbacks on exit.
- Expose global state for the currently-running session.
"""

import datetime
import json
import os
import pathlib
import subprocess
import threading
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Global state for the currently-running Webots process
# ---------------------------------------------------------------------------

"""
根据架构，当前仅支持单Webots模拟进程
todo: 多线程支持
"""
_lock = threading.Lock()
_current_proc: Optional[subprocess.Popen] = None
_current_session_id: Optional[str] = None


def get_current_proc() -> Optional[subprocess.Popen]:
    with _lock:
        return _current_proc


def get_current_session_id() -> Optional[str]:
    with _lock:
        return _current_session_id


def set_current_proc(
    proc: Optional[subprocess.Popen], session_id: Optional[str]
) -> None:
    global _current_proc, _current_session_id
    with _lock:
        _current_proc = proc
        _current_session_id = session_id


def kill_current_proc() -> None:
    """Terminate the running Webots process if one exists."""
    with _lock:
        proc = _current_proc
    if proc is not None:
        try:
            proc.terminate()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Race config writer
# ---------------------------------------------------------------------------


def write_race_config(
    session_id: str,
    session_type: str,
    total_laps: int,
    cars: list[dict],
    recording_path: str,
    race_config_path: str,
) -> None:
    """
    Write race_config.json and create the recordings/{session_id}/ directory.

    ``recording_path`` is stored with forward slashes so Webots (Linux-style
    path handling inside controllers) can read it cross-platform.

    ``cars`` is a list of dicts with keys:
        car_node_id, team_id, team_name, code_path, start_position
    """
    # Normalise recording path to forward slashes
    recording_path_fwd = recording_path.replace("\\", "/")

    config = {
        "session_id": session_id,
        "session_type": session_type,
        "total_laps": total_laps,
        "recording_path": recording_path_fwd,
        "cars": cars,
        "created_at": datetime.datetime.now().isoformat(),
    }

    # Ensure the per-session recordings directory exists
    recordings_session_dir = pathlib.Path(recording_path)
    recordings_session_dir.mkdir(parents=True, exist_ok=True)

    with open(race_config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Webots launcher
# ---------------------------------------------------------------------------


def start_webots(
    webots_binary: str,
    world_file: str,
    race_config_path: str,
    minimize: bool = False,
) -> subprocess.Popen:
    """
    Launch Webots with RACE_CONFIG_PATH set in the environment.

    Returns the Popen object; does NOT block.
    """
    env = os.environ.copy()
    env["RACE_CONFIG_PATH"] = race_config_path

    args = [webots_binary]
    if minimize:
        args += ["--minimize", "--no-rendering"]
    args.append(world_file)

    proc = subprocess.Popen(args, env=env)
    return proc


# ---------------------------------------------------------------------------
# Process monitor
# ---------------------------------------------------------------------------


def monitor_webots(
    proc: subprocess.Popen,
    session_id: str,
    recordings_dir: str,
    on_finished: Callable[[str], None],
    on_aborted: Callable[[str], None],
) -> threading.Thread:
    """
    Start a daemon thread that waits for *proc* to exit, then calls either
    ``on_finished(session_id)`` (if metadata.json was written) or
    ``on_aborted(session_id)``.

    Returns the thread (already started).
    """

    def _watch() -> None:
        proc.wait()
        metadata_path = pathlib.Path(recordings_dir) / session_id / "metadata.json"
        if metadata_path.exists():
            on_finished(session_id)
        else:
            on_aborted(session_id)

    t = threading.Thread(
        target=_watch, daemon=True, name=f"webots-monitor-{session_id}"
    )
    t.start()
    return t

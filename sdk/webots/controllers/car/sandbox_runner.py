#!/usr/bin/env python3
"""
Sandbox runner — executes student team_controller.py with restricted imports.

Protocol (binary, over stdin/stdout):
  IN  per frame:
    4 bytes  little-endian uint32  — left image byte length
    N bytes                        — left BGR image (H x W x 3, uint8, row-major)
    4 bytes  little-endian uint32  — right image byte length
    M bytes                        — right BGR image (H x W x 3, uint8, row-major)
    8 bytes  little-endian float64 — simulation timestamp (seconds)
  OUT per frame:
    one JSON line: {"steering": float, "speed": float}\n

Exit codes:
  0 — clean shutdown (stdin closed)
  1 — student code failed to load (non-import error)
  2 — student code triggered a blocked import (ImportError from hook)

多车并发说明：
  当 race_config.json 中包含多辆车（cars[] 数组）时，每辆车的 sandbox_runner
  进程通过环境变量 CAR_ID 确定自身对应的配置条目：
    - RACE_CONFIG_PATH：race_config.json 的绝对路径
    - CAR_ID：该进程对应的 car_id（如 car_0、car_1）
  CAR_ID 未设置或无法在 cars[] 中找到时，进程以非零码退出并输出明确错误信息。
  多实例并发时各 runner 为独立进程，互不干扰。
"""

import os
import sys
import argparse
import struct
import json
import importlib.abc
import importlib.util

# ---------------------------------------------------------------------------
# Parse arguments BEFORE installing the import hook so argparse itself is safe
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="AI Racer sandbox runner")
parser.add_argument('--team-id',   required=False, default=None, help="Team identifier")
parser.add_argument('--code-path', required=False, default=None,
                    help="Absolute path to team_controller.py "
                         "(可选：未指定时从 RACE_CONFIG_PATH + CAR_ID 自动解析)")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# 若 --code-path 未指定，则从 RACE_CONFIG_PATH + CAR_ID 环境变量解析
# ---------------------------------------------------------------------------

_resolved_code_path: str = args.code_path or ""
_resolved_team_id: str = args.team_id or ""

if not _resolved_code_path:
    _race_config_path = os.environ.get("RACE_CONFIG_PATH", "")
    _car_id = os.environ.get("CAR_ID", "")

    if not _race_config_path:
        print(
            "[Sandbox][error] --code-path 未指定且环境变量 RACE_CONFIG_PATH 未设置。"
            "请通过 --code-path 或 RACE_CONFIG_PATH + CAR_ID 提供控制器路径。",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _car_id:
        print(
            "[Sandbox][error] --code-path 未指定且环境变量 CAR_ID 未设置。"
            "多车模式下必须通过 CAR_ID 指定当前进程对应的车辆标识。",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with open(_race_config_path, encoding="utf-8") as _f:
            _race_cfg = json.load(_f)
    except FileNotFoundError:
        print(
            f"[Sandbox][error] RACE_CONFIG_PATH 指向的文件不存在: {_race_config_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    except json.JSONDecodeError as _e:
        print(
            f"[Sandbox][error] RACE_CONFIG_PATH 文件不是合法 JSON: {_race_config_path} ({_e})",
            file=sys.stderr,
        )
        sys.exit(1)

    _cars = _race_cfg.get("cars", [])
    _matched = None
    for _car in _cars:
        if _car.get("car_id") == _car_id:
            _matched = _car
            break

    if _matched is None:
        _available = [c.get("car_id", "?") for c in _cars]
        print(
            f"[Sandbox][error] CAR_ID={_car_id!r} 在 race_config.json 的 cars[] 中未找到匹配条目。"
            f"可用 car_id: {_available}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 优先使用新格式字段 controller_path，兼容旧格式字段 code_path
    _resolved_code_path = _matched.get("controller_path") or _matched.get("code_path", "")
    if not _resolved_code_path:
        print(
            f"[Sandbox][error] cars[] 中 car_id={_car_id!r} 的条目缺少 "
            "controller_path / code_path 字段。",
            file=sys.stderr,
        )
        sys.exit(1)

    # 若 team_id 也未从命令行传入，尝试从配置中读取
    if not _resolved_team_id:
        _resolved_team_id = (
            _matched.get("team") or _matched.get("team_id", "unknown")
        )

# 统一变量名，后续代码不再区分来源
args.code_path = _resolved_code_path
args.team_id = _resolved_team_id

# ---------------------------------------------------------------------------
# Import numpy BEFORE the hook (sandbox_runner itself needs it)
# ---------------------------------------------------------------------------

import numpy as np  # noqa: E402

# ---------------------------------------------------------------------------
# Import hook — blocks dangerous standard-library and network modules
# ---------------------------------------------------------------------------

# NOTE: 此黑白名单必须与 sdk/car_sandbox.py 及 sdk/rules.yaml 保持一致。
# 修改时请同步三处；sdk/tests/test_consistency.py 会做一致性断言。
BLOCKED_PREFIXES: frozenset = frozenset([
    'os', 'sys', 'socket', 'subprocess', 'multiprocessing',
    'threading', 'time', 'datetime', 'io', 'builtins',
    'ctypes', 'winreg', 'nt', '_winapi',
    'shutil', 'tempfile', 'glob', 'fnmatch',
    'requests', 'urllib', 'http', 'ftplib', 'smtplib',
    'signal', 'gc', 'inspect', 'importlib',
])

# 与 car_sandbox.py::_ALLOWED_MODULES 对齐的白名单（用于自检 / 错误提示）。
ALLOWED_BASES: frozenset = frozenset([
    'numpy', 'np', 'cv2', 'math', 'collections',
    'heapq', 'functools', 'itertools',
    'typing', '__future__', 'pathlib', 'dataclasses', 're',
])


class SandboxImportHook(importlib.abc.MetaPathFinder):
    """Raise ImportError for any module whose top-level name is in BLOCKED_PREFIXES."""

    def find_spec(self, fullname, path, target=None):
        base = fullname.split('.')[0]
        if base in BLOCKED_PREFIXES:
            raise ImportError(
                f"[Sandbox] '{fullname}' is not allowed in student code. "
                f"Allowed libraries: numpy, cv2, math, collections, "
                f"heapq, functools, itertools, typing, __future__, pathlib, dataclasses, re."
            )
        return None  # not intercepted — fall through to the next finder


sys.meta_path.insert(0, SandboxImportHook())

# ---------------------------------------------------------------------------
# Load student code (hook is now active)
# ---------------------------------------------------------------------------

try:
    spec   = importlib.util.spec_from_file_location("team_controller", args.code_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    control_fn = module.control
except ImportError as e:
    print(f"[Sandbox] Import blocked while loading student code: {e}", file=sys.stderr)
    sys.exit(2)
except Exception as e:
    print(f"[Sandbox] Failed to load student code: {e}", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Main loop — read frames, call control(), write results
# ---------------------------------------------------------------------------

IMG_H, IMG_W, IMG_C = 480, 640, 3

while True:
    try:
        # --- Read left image ---
        hdr = sys.stdin.buffer.read(4)
        if len(hdr) < 4:
            break
        left_len   = struct.unpack('<I', hdr)[0]
        left_bytes = sys.stdin.buffer.read(left_len)
        if len(left_bytes) < left_len:
            break

        # --- Read right image ---
        hdr2 = sys.stdin.buffer.read(4)
        if len(hdr2) < 4:
            break
        right_len   = struct.unpack('<I', hdr2)[0]
        right_bytes = sys.stdin.buffer.read(right_len)
        if len(right_bytes) < right_len:
            break

        # --- Read timestamp ---
        ts_bytes = sys.stdin.buffer.read(8)
        if len(ts_bytes) < 8:
            break
        timestamp = struct.unpack('<d', ts_bytes)[0]

        # --- Reconstruct BGR arrays ---
        left_img  = np.frombuffer(left_bytes,  dtype=np.uint8).reshape((IMG_H, IMG_W, IMG_C)).copy()
        right_img = np.frombuffer(right_bytes, dtype=np.uint8).reshape((IMG_H, IMG_W, IMG_C)).copy()

    except Exception as e:
        print(f"[Sandbox] Read error: {e}", file=sys.stderr)
        break

    # --- Call student control function ---
    try:
        result   = control_fn(left_img, right_img, timestamp)
        steering = float(max(-1.0, min(1.0, result[0])))
        speed    = float(max(0.0,  min(1.0, result[1])))
    except Exception as e:
        print(f"[Sandbox] control() raised an exception: {e}", file=sys.stderr)
        steering, speed = 0.0, 0.0

    # --- Write JSON response line ---
    line = json.dumps({"steering": steering, "speed": speed}) + '\n'
    sys.stdout.buffer.write(line.encode())
    sys.stdout.buffer.flush()

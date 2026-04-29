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
"""

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
parser.add_argument('--team-id',   required=True,  help="Team identifier")
parser.add_argument('--code-path', required=True,  help="Absolute path to team_controller.py")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Import numpy BEFORE the hook (sandbox_runner itself needs it)
# ---------------------------------------------------------------------------

import numpy as np  # noqa: E402

# ---------------------------------------------------------------------------
# Import hook — blocks dangerous standard-library and network modules
# ---------------------------------------------------------------------------

BLOCKED_PREFIXES: frozenset = frozenset([
    'os', 'sys', 'socket', 'subprocess', 'multiprocessing',
    'threading', 'time', 'datetime', 'io', 'builtins',
    'ctypes', 'winreg', 'nt', '_winapi', 'pathlib',
    'shutil', 'tempfile', 'glob', 'fnmatch',
    'requests', 'urllib', 'http', 'ftplib', 'smtplib',
    'signal', 'gc', 'inspect', 'importlib',
])


class SandboxImportHook(importlib.abc.MetaPathFinder):
    """Raise ImportError for any module whose top-level name is in BLOCKED_PREFIXES."""

    def find_spec(self, fullname, path, target=None):
        base = fullname.split('.')[0]
        if base in BLOCKED_PREFIXES:
            raise ImportError(
                f"[Sandbox] '{fullname}' is not allowed in student code. "
                f"Allowed libraries include: numpy, cv2, math, collections, "
                f"heapq, functools, itertools."
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

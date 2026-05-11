"""Small wrapper to start a local Webots race using the project's SDK.

This script calls `sdk/run_local.py` in this repository with sensible
defaults so you can start a local race with a single command.

Requirements:
- Python (same interpreter used to run this script)
- Webots installed and discoverable (or pass --webots)

Usage examples:
  # Quick start (uses sdk/my_controller.py and default world):
  python local_test/run.py

  # Specify Webots executable explicitly:
  python local_test/run.py --webots "C:\\Program Files\\Webots\\webots.exe"

  # Run a specific world / team / car slot:
  python local_test/run.py --world track_complex --team-id local_team --car-slot car_1

The script simply delegates to sdk/run_local.py, so all options supported
by that script are available. See sdk/run_local.py --help for more.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SDK_RUN = REPO_ROOT / "sdk" / "run_local.py"
DEFAULT_CODE = REPO_ROOT / "sdk" / "my_controller.py"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Start a local AI Racer Webots session")
    p.add_argument("--webots", help="Path to Webots executable (optional)")
    p.add_argument("--team-id", default="local_team", help="Team id to use")
    p.add_argument("--car-slot", default="car_1", help="Car slot to use (car_1, car_2, ...)" )
    p.add_argument("--world", default="track_complex", help="World short name or .wbt path (default: track_complex)")
    p.add_argument("--fast", action="store_true", help="Start Webots in fast mode (--mode=fast)")
    p.add_argument("--minimize", action="store_true", help="Start Webots minimized")
    p.add_argument("--batch", action="store_true", help="Start Webots in batch mode")
    p.add_argument("--skip-validate", action="store_true", help="Skip controller validation")
    p.add_argument("--list-worlds", action="store_true", help="List available worlds (delegates to sdk/run_local.py)")
    return p


def main() -> int:
    args = build_parser().parse_args()

    if not SDK_RUN.is_file():
        print(f"[local_test] cannot find sdk/run_local.py at {SDK_RUN}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(SDK_RUN)]
    if args.list_worlds:
        cmd.append("--list-worlds")
    else:
        cmd += ["--code-path", str(DEFAULT_CODE), "--team-id", args.team_id, "--car-slot", args.car_slot, "--world", args.world]
        if args.webots:
            cmd += ["--webots", args.webots]
        if args.fast:
            cmd.append("--fast")
        if args.minimize:
            cmd.append("--minimize")
        if args.batch:
            cmd.append("--batch")
        if args.skip_validate:
            cmd.append("--skip-validate")

    print(f"[local_test] running: {' '.join(cmd)}")
    rc = subprocess.call(cmd)
    return rc


if __name__ == '__main__':
    sys.exit(main())


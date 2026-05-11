"""
Standalone runner for the self-contained `local_test` folder.

Generates a minimal `race_config.json` and launches Webots with the local
`webots` project as working directory so controllers/protos are discovered.

Usage:
  python local_test/standalone_run.py [--webots PATH] [--race-id ID]

If `--webots` is not given the script will try to find `webots` on PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime


ROOT = Path(__file__).resolve().parent
WEBOTS_DIR = ROOT / 'webots'
WORLD = WEBOTS_DIR / 'worlds' / 'track_complex.wbt'
RACE_CONFIG = ROOT / 'race_config.json'


def find_webots(explicit: str | None) -> str | None:
    if explicit:
        if Path(explicit).is_file():
            return explicit
        print(f"[standalone_run] specified Webots not found: {explicit}", file=sys.stderr)
        return None
    found = shutil.which('webots') or shutil.which('webots.exe')
    return found


def make_config(race_id: str) -> None:
    rec_dir = str((ROOT / 'recordings' / race_id).resolve())
    os.makedirs(rec_dir, exist_ok=True)
    cfg = {
        'race_id': race_id,
        'session_type': 'test',
        'total_laps': 1,
        'recording_path': rec_dir,
        'cars': [
            {
                'team_id': 'local_team',
                'team_name': 'local_team',
                'car_slot': 'car_1',
                'code_path': '',
            }
        ],
        'overhead_height': 30.0,
    }
    with open(RACE_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--webots', help='Path to webots executable')
    p.add_argument('--race-id', default=f'local_{datetime.now().strftime("%Y%m%d_%H%M%S")}', help='Race id')
    args = p.parse_args()

    webots = find_webots(args.webots)
    if webots is None:
        print('[standalone_run] Webots not found; please install Webots or pass --webots', file=sys.stderr)
        return 1

    if not WORLD.is_file():
        print(f'[standalone_run] world file missing: {WORLD}', file=sys.stderr)
        return 1

    make_config(args.race_id)

    env = os.environ.copy()
    env['RACE_CONFIG_PATH'] = str(RACE_CONFIG.resolve())

    cmd = [webots, str(WORLD.resolve())]
    print(f'[standalone_run] launching: {cmd} (cwd={WEBOTS_DIR})')
    rc = subprocess.call(cmd, env=env, cwd=str(WEBOTS_DIR))
    return rc


if __name__ == '__main__':
    sys.exit(main())


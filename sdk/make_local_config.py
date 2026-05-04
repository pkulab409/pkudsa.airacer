"""Generate a sample race_config JSON for local Webots runs.
Usage:
    # 单车模式
    python sdk/make_local_config.py --code-path PATH [--team-id ID] [--car-slot NAME] [--out FILE]
    # 多车模式（可重复使用 --car 参数）
    python sdk/make_local_config.py \
        --car car_0:team_a:/path/to/team_a_controller.py \
        --car car_1:team_b:/path/to/team_b_controller.py \
        --out sdk/local_race_config.json
    # 追加到已有配置
    python sdk/make_local_config.py --code-path PATH --team-id new_team --append
The produced JSON contains a `cars` list that `car_controller.py` reads.
Edit the produced file to set absolute paths if necessary.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
from typing import Any
DEFAULT_OUT = "sdk/local_race_config.json"
def validate_code_path(code_path: str) -> pathlib.Path:
    """Validate that the controller script exists and is a .py file."""
    p = pathlib.Path(code_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Code path does not exist: {p}")
    if not p.is_file():
        raise ValueError(f"Code path is not a file: {p}")
    if p.suffix != ".py":
        print(f"[warn] Code path does not end with .py: {p}", file=sys.stderr)
    return p.resolve()
def parse_car_spec(spec: str) -> dict[str, str]:
    """Parse a --car argument in the form 'car_slot:team_id:code_path'."""
    parts = spec.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"Invalid --car spec: {spec!r}. "
            "Expected format 'car_slot:team_id:code_path'"
        )
    car_slot, team_id, code_path = (s.strip() for s in parts)
    if not all([car_slot, team_id, code_path]):
        raise argparse.ArgumentTypeError(
            f"Invalid --car spec: {spec!r}. All three fields must be non-empty."
        )
    resolved = validate_code_path(code_path)
    return {
        "car_slot": car_slot,
        "team_id": team_id,
        "code_path": str(resolved),
    }
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a race_config JSON for local Webots runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # 单车模式
    parser.add_argument("--code-path", help="Path to team_controller.py (single-car mode)")
    parser.add_argument("--team-id", default="demo_team", help="Team id (default: demo_team)")
    parser.add_argument(
        "--car-slot",
        default="car_1",
        help="Robot node name in the world (default: car_1, matching "
             "simnode/webots/worlds/airacer.wbt)",
    )
    # 多车模式
    parser.add_argument(
        "--car",
        action="append",
        default=[],
        metavar="SLOT:TEAM:PATH",
        help="Add a car entry (can be specified multiple times). "
        "Format: 'car_slot:team_id:code_path'",
    )
    # 输出控制
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"Output JSON path (default: {DEFAULT_OUT})")
    parser.add_argument(
        "--force", action="store_true", help="Overwrite output file if it already exists"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append cars to existing config file instead of overwriting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated JSON to stdout without writing any file",
    )
    return parser
def collect_cars(args: argparse.Namespace) -> list[dict[str, str]]:
    """Collect car entries from CLI arguments."""
    cars: list[dict[str, str]] = []
    # 多车模式
    for spec in args.car:
        cars.append(parse_car_spec(spec))
    # 单车模式
    if args.code_path:
        resolved = validate_code_path(args.code_path)
        cars.append(
            {
                "car_slot": args.car_slot,
                "team_id": args.team_id,
                "code_path": str(resolved),
            }
        )
    if not cars:
        raise ValueError(
            "No car configuration provided. Use --code-path or --car to specify at least one car."
        )
    # 检查 car_slot 重复
    slots = [c["car_slot"] for c in cars]
    duplicates = {s for s in slots if slots.count(s) > 1}
    if duplicates:
        raise ValueError(f"Duplicate car_slot values detected: {sorted(duplicates)}")
    return cars
def load_existing(path: pathlib.Path) -> dict[str, Any]:
    """Load an existing config file, or return an empty skeleton."""
    if not path.exists():
        return {"cars": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Existing config file is not valid JSON: {path} ({e})") from e
    if not isinstance(data, dict) or not isinstance(data.get("cars"), list):
        raise ValueError(f"Existing config file has unexpected structure: {path}")
    return data
def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        new_cars = collect_cars(args)
    except (FileNotFoundError, ValueError, argparse.ArgumentTypeError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    outp = pathlib.Path(args.out).expanduser()
    # 构造最终配置
    if args.append:
        try:
            cfg = load_existing(outp)
        except ValueError as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
        existing_slots = {c.get("car_slot") for c in cfg["cars"]}
        for car in new_cars:
            if car["car_slot"] in existing_slots:
                print(
                    f"[error] car_slot {car['car_slot']!r} already exists in {outp}. "
                    "Use a different slot or remove --append.",
                    file=sys.stderr,
                )
                return 1
        cfg["cars"].extend(new_cars)
    else:
        cfg = {"cars": new_cars}
    rendered = json.dumps(cfg, indent=2, ensure_ascii=False)
    if args.dry_run:
        print(rendered)
        return 0
    if outp.exists() and not args.force and not args.append:
        print(
            f"[error] Output file already exists: {outp}\n"
            "       Use --force to overwrite or --append to add to it.",
            file=sys.stderr,
        )
        return 1
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(rendered + "\n", encoding="utf-8")
    print(f"[ok] Wrote {len(cfg['cars'])} car(s) to: {outp.resolve()}")
    for car in cfg["cars"]:
        print(f"     - {car['car_slot']}  team={car['team_id']}  code={car['code_path']}")
    return 0
if __name__ == "__main__":
    sys.exit(main())
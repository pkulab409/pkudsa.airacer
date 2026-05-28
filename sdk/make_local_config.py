"""Generate a sample race_config JSON for local Webots runs.
Usage:
    # 单车模式
    python sdk/make_local_config.py --code-path PATH [--team-id ID] [--car-slot NAME] [--out FILE]
    # 多车模式（可重复使用 --car 参数，格式 car_slot:team_id:code_path）
    python sdk/make_local_config.py \
        --car car_1:team_a:/path/to/team_a_controller.py \
        --car car_2:team_b:/path/to/team_b_controller.py \
        --out sdk/.local/race_config.json
    # run_local.py 内部多车模式（--car-multi，格式 car_id:slot:team:controller_path）
    python sdk/make_local_config.py \
        --world basic \
        --car-multi car_0:car_1:red:/abs/path/a.py \
        --car-multi car_1:car_2:blue:/abs/path/b.py \
        --out sdk/.local/race_config.json --force
    # 追加到已有配置
    python sdk/make_local_config.py --code-path PATH --team-id new_team --append

输出 JSON 顶层结构（新格式）：
    {
      "world": "<world_name>",
      "cars": [
        { "car_id": "car_0", "slot": "car_1", "team": "red", "controller_path": "/abs/path/a.py" },
        ...
      ]
    }
兼容旧格式：单车调用时 cars[] 长度为 1，同时保留 car_slot/team_id/code_path 字段供老版
supervisor.py 读取。
The produced JSON contains a `cars` list that `car_controller.py` reads.
Edit the produced file to set absolute paths if necessary.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
from typing import Any
DEFAULT_OUT = "sdk/.local/race_config.json"

SDK_DIR = pathlib.Path(__file__).resolve().parent


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
    """Parse a --car argument.

    支持两种格式（以冒号分隔）：
      * ``car_slot:team_id:code_path``                —— 3 段，无车型注释
      * ``car_slot:team_id:code_path:car_model``      —— 4 段，最后一段是车型（仅注释用）

    返回字典同时包含新格式字段（car_id/slot/team/controller_path）和老格式字段
    （car_slot/team_id/code_path）以保证向下兼容。
    """
    parts = spec.split(":", 3)
    if len(parts) not in (3, 4):
        raise argparse.ArgumentTypeError(
            f"Invalid --car spec: {spec!r}. "
            "Expected 'car_slot:team_id:code_path' or "
            "'car_slot:team_id:code_path:car_model'"
        )
    if len(parts) == 3:
        car_slot, team_id, code_path = (s.strip() for s in parts)
        car_model = ""
    else:
        car_slot, team_id, code_path, car_model = (s.strip() for s in parts)
    if not all([car_slot, team_id, code_path]):
        raise argparse.ArgumentTypeError(
            f"Invalid --car spec: {spec!r}. "
            "car_slot / team_id / code_path 必须非空。"
        )
    resolved = validate_code_path(code_path)
    entry: dict[str, str] = {
        # 新格式字段
        "car_id": car_slot,          # --car 模式下 car_id 默认等同于 car_slot
        "slot": car_slot,
        "team": team_id,
        "controller_path": str(resolved),
        # 老格式兼容字段
        "car_slot": car_slot,
        "team_id": team_id,
        "team_name": team_id,        # supervisor 需要 team_name；本地无独立显示名时沿用 team_id
        "code_path": str(resolved),
    }
    if car_model:
        entry["car_model"] = car_model
    return entry


def parse_car_multi_spec(spec: str) -> dict[str, str]:
    """Parse a --car-multi argument（由 run_local.py 内部调用）。

    格式：``car_id:slot:team:controller_path``（4 段，均必填）
    返回字典同时包含新格式字段和老格式字段以保证向下兼容。
    """
    # controller_path 本身可能含冒号（Windows 盘符），因此最多分 4 段
    parts = spec.split(":", 3)
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"Invalid --car-multi spec: {spec!r}. "
            "Expected 'car_id:slot:team:controller_path'"
        )
    car_id, slot, team, code_path = (s.strip() for s in parts)
    if not all([car_id, slot, team, code_path]):
        raise argparse.ArgumentTypeError(
            f"Invalid --car-multi spec: {spec!r}. "
            "car_id / slot / team / controller_path 均必须非空。"
        )
    resolved = validate_code_path(code_path)
    return {
        # 新格式字段
        "car_id": car_id,
        "slot": slot,
        "team": team,
        "controller_path": str(resolved),
        # 老格式兼容字段
        "car_slot": slot,
        "team_id": team,
        "team_name": team,
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
        "--team-name",
        default=None,
        help="Team display name for supervisor (default: same as --team-id)",
    )
    parser.add_argument(
        "--car-slot",
        default="car_1",
        help="Robot node name in the world (default: car_1). "
             "Run `python sdk/run_local.py --list-worlds` to see the "
             "slot -> car-model mapping per track.",
    )
    parser.add_argument(
        "--car-model",
        default=None,
        help="Car PROTO type associated with --car-slot (informational, "
             "e.g. CarPhoenix / CarThunder / ...). Auto-filled by run_local.py.",
    )
    # Session 级字段（supervisor.py 需要）
    parser.add_argument("--race-id", default="local_race",
                        help="Race/session id for supervisor (default: local_race)")
    parser.add_argument("--session-type", default="practice",
                        help="Session type label (default: practice)")
    parser.add_argument("--total-laps", type=int, default=1,
                        help="Total laps for this session (default: 1)")
    parser.add_argument("--recording-path", default=None,
                        help="Telemetry recording output directory "
                             "(supervisor writes telemetry.jsonl + live_view.jpg "
                             "inside it; default: <repo_root>/.local/recordings/)")
    # 赛道名（写入 race_config.json 顶层）
    parser.add_argument(
        "--world",
        default="",
        help="World/track short name to embed in race_config.json (e.g. basic / complex).",
    )
    # 多车模式（旧格式：car_slot:team_id:code_path）
    parser.add_argument(
        "--car",
        action="append",
        default=[],
        metavar="SLOT:TEAM:PATH",
        help="Add a car entry (can be specified multiple times). "
        "Format: 'car_slot:team_id:code_path'",
    )
    # 多车模式（新格式：car_id:slot:team:controller_path，由 run_local.py 内部使用）
    parser.add_argument(
        "--car-multi",
        action="append",
        default=[],
        metavar="CAR_ID:SLOT:TEAM:PATH",
        help="Add a car entry in new multi-car format (used internally by run_local.py). "
        "Format: 'car_id:slot:team:controller_path'",
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
    """Collect car entries from CLI arguments.

    处理优先级（从高到低）：
      1. --car-multi（新格式，run_local.py 内部调用）
      2. --car（旧格式，用户直接调用 make_local_config.py）
      3. --code-path（单车兼容模式）

    若同时传入 --car-multi 和 --car，两者均会被收集（分别解析后合并）。
    未显式指定 car_id 时自动生成（car_0, car_1, ...）。
    """
    cars: list[dict[str, str]] = []

    # 新格式多车（--car-multi）
    for spec in args.car_multi:
        cars.append(parse_car_multi_spec(spec))

    # 旧格式多车（--car）
    for spec in args.car:
        cars.append(parse_car_spec(spec))

    # 单车兼容模式（--code-path）
    if args.code_path:
        resolved = validate_code_path(args.code_path)
        team_name = args.team_name if args.team_name else args.team_id
        entry: dict[str, str] = {
            # 新格式字段（car_id 在单车模式下默认为 car_slot）
            "car_id": args.car_slot,
            "slot": args.car_slot,
            "team": args.team_id,
            "controller_path": str(resolved),
            # 老格式兼容字段
            "car_slot": args.car_slot,
            "team_id": args.team_id,
            "team_name": team_name,
            "code_path": str(resolved),
        }
        if args.car_model:
            entry["car_model"] = args.car_model
        cars.append(entry)

    if not cars:
        raise ValueError(
            "No car configuration provided. Use --code-path or --car to specify at least one car."
        )

    # 对未显式设置 car_id 的条目（不应出现，但防御性处理）自动补全
    for i, car in enumerate(cars):
        if not car.get("car_id"):
            car["car_id"] = f"car_{i}"

    # 检查 car_id 唯一性
    ids = [c["car_id"] for c in cars]
    dup_ids = {v for v in ids if ids.count(v) > 1}
    if dup_ids:
        raise ValueError(f"Duplicate car_id values detected: {sorted(dup_ids)}")

    # 检查 slot 重复
    slots = [c.get("slot") or c.get("car_slot", "") for c in cars]
    duplicates = {s for s in slots if slots.count(s) > 1}
    if duplicates:
        raise ValueError(f"Duplicate slot values detected: {sorted(duplicates)}")

    return cars
def _default_recording_path() -> str:
    """Default telemetry recording directory.

    Note: ``recording_path`` is used by supervisor.py as a *directory* (it calls
    ``os.makedirs(recording_path)`` and writes ``telemetry.jsonl`` /
    ``live_view.jpg`` inside). Must not point at a file.

    Windows note: Webots' C++ ``Camera.saveImage()`` uses narrow-char ``fopen``
    which fails on paths containing non-ASCII characters (e.g. a repo placed
    under "课程/大一下/…"). If the sdk directory itself is non-ASCII, we fall
    back to a pure-ASCII path under ``%TEMP%`` (which on Windows is an 8.3
    short path even when the username is non-ASCII).
    """
    import tempfile
    # sdk/make_local_config.py → sdk/
    sdk_dir = pathlib.Path(__file__).resolve().parent
    sdk_default = sdk_dir / ".local" / "recordings"
    if str(sdk_default).isascii():
        return str(sdk_default)
    # SDK 路径含非 ASCII —— Webots saveImage 会失败，落到系统临时目录
    return str(pathlib.Path(tempfile.gettempdir()) / "airacer_local" / "recordings")


def _build_session_meta(args: argparse.Namespace) -> dict[str, Any]:
    """Build the top-level session fields required by supervisor.py."""
    rec = args.recording_path if args.recording_path else _default_recording_path()
    return {
        "race_id": args.race_id,
        "session_type": args.session_type,
        "total_laps": int(args.total_laps),
        "recording_path": str(pathlib.Path(rec).expanduser().resolve()),
    }


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
    session_meta = _build_session_meta(args)
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
        # 追加模式：如原文件缺少 session 字段（老版本配置），补齐默认值
        for k, v in session_meta.items():
            cfg.setdefault(k, v)
    else:
        cfg = {**session_meta, "cars": new_cars}
    # 将 world 写入顶层（若调用方未传入则为空字符串，不强制要求）
    world_val = getattr(args, "world", "") or ""
    if world_val:
        cfg["world"] = world_val
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
    # 确保 recording_path 目录本身存在（supervisor.py 会 os.makedirs 但提前建好更稳）
    try:
        pathlib.Path(cfg["recording_path"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    outp.write_text(rendered + "\n", encoding="utf-8")
    print(f"[ok] Wrote {len(cfg['cars'])} car(s) to: {outp.resolve()}")
    print(f"     race_id={cfg.get('race_id')}  session_type={cfg.get('session_type')}"
          f"  total_laps={cfg.get('total_laps')}")
    if cfg.get("world"):
        print(f"     world={cfg['world']}")
    for car in cfg["cars"]:
        extra = f"  car_model={car['car_model']}" if car.get("car_model") else ""
        car_id = car.get("car_id") or car.get("car_slot", "?")
        slot = car.get("slot") or car.get("car_slot", "?")
        team = car.get("team") or car.get("team_id", "?")
        code = car.get("controller_path") or car.get("code_path", "?")
        print(f"     - car_id={car_id}  slot={slot}  team={team}"
              f"  code={code}{extra}")
    return 0
if __name__ == "__main__":
    sys.exit(main())
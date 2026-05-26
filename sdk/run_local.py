"""run_local.py — AI Racer 本地一键启动脚本

把"校验代码 → 生成 race_config.json → 启动 Webots"三步封装成一条命令，
降低学生首次上手门槛。

典型用法
--------
# 最小用法：使用默认模板 + 默认世界（basic 椭圆赛道，车位 car_1 = CarPhoenix）
python sdk/run_local.py --code-path sdk/my_controller.py

# 指定队伍 ID / 车位 / 赛道（短名）
python sdk/run_local.py \
    --code-path sdk/my_controller.py \
    --team-id my_team \
    --car-slot car_2 \
    --world complex

# 多车并发用法（--car 可重复，格式 controller_path:slot:team）
python sdk/run_local.py \
    --world basic \
    --car sdk/example_controller.py:car_1:red \
    --car sdk/my_controller.py:car_2:blue

# 查看所有可用赛道和车型
python sdk/run_local.py --list-worlds

# 只跑校验，不启动 Webots（CI / 提交前自检）
python sdk/run_local.py --code-path sdk/my_controller.py --validate-only

# 不做校验直接跑（已知代码通过校验时使用）
python sdk/run_local.py --code-path sdk/my_controller.py --skip-validate

退出码
------
0  — 校验通过且（如非 --validate-only）Webots 正常退出
1  — 参数错误 / 文件缺失 / Webots 未找到
2  — 控制器校验失败
3  — Webots 进程非 0 退出
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Optional

# SDK 内部模块（同目录导入）
SDK_DIR = pathlib.Path(__file__).resolve().parent
# 保留 REPO_ROOT 别名：历史上指仓库根，现在 SDK 自包含，等同于 SDK_DIR。
REPO_ROOT = SDK_DIR

# 赛道/车型目录（单一信息源，见 sdk/worlds.py）
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))
from worlds import (  # noqa: E402
    DEFAULT_WORLD_KEY,
    WORLDS,
    format_catalog,
    resolve_world,
)

DEFAULT_WORLD = WORLDS[DEFAULT_WORLD_KEY].path
# 生成的临时 race_config 落在 sdk/.local/，纯 ASCII 且不污染其他目录
DEFAULT_CONFIG = SDK_DIR / ".local" / "race_config.json"


# ---------------------------------------------------------------------------
# 子步骤封装
# ---------------------------------------------------------------------------

def _run_validator(code_path: pathlib.Path, rules_path: Optional[pathlib.Path]) -> int:
    """调用 validate_controller.py，返回其退出码。"""
    cmd = [sys.executable, str(SDK_DIR / "validate_controller.py"),
           "--code-path", str(code_path)]
    if rules_path is not None:
        cmd += ["--rules", str(rules_path)]
    print(f"[run_local] 校验: {' '.join(cmd)}")
    return subprocess.call(cmd)


def _validate_cars(
    cars: list[dict],
    rules_path: Optional[pathlib.Path],
) -> int:
    """对车辆列表中每辆车依次调用校验器，任一失败立即返回非零退出码。

    Returns:
        0  — 全部通过
        2  — 某辆车校验失败（与原单车校验退出码一致）
    """
    for i, car in enumerate(cars):
        code_path = pathlib.Path(car["controller_path"])
        car_id = car.get("car_id", f"car_{i}")
        print(f"[run_local] 校验车辆 {car_id} ({code_path.name}) ...")
        rc = _run_validator(code_path, rules_path)
        if rc != 0:
            print(
                f"[run_local][error] 车辆 {car_id} ({code_path}) 校验失败（退出码 {rc}）。",
                file=sys.stderr,
            )
            return 2
    return 0


def _make_config_multi(
    cars: list[dict],
    world_key: str,
    out_path: pathlib.Path,
) -> int:
    """调用 make_local_config.py 生成多车 race_config.json。

    cars 中每项须包含 car_id / slot / team / controller_path。
    """
    cmd = [
        sys.executable, str(SDK_DIR / "make_local_config.py"),
        "--world", world_key,
        "--out", str(out_path),
        "--force",
    ]
    for car in cars:
        # 格式：car_id:slot:team:controller_path（make_local_config 的 --car 格式扩展）
        spec = f"{car['car_id']}:{car['slot']}:{car['team']}:{car['controller_path']}"
        cmd += ["--car-multi", spec]
    print(f"[run_local] 生成多车配置: {' '.join(cmd)}")
    return subprocess.call(cmd)


def _make_config(
    code_path: pathlib.Path,
    team_id: str,
    car_slot: str,
    out_path: pathlib.Path,
    car_model: Optional[str] = None,
) -> int:
    """调用 make_local_config.py 生成 race_config.json（单车兼容接口）。"""
    cmd = [
        sys.executable, str(SDK_DIR / "make_local_config.py"),
        "--code-path", str(code_path),
        "--team-id", team_id,
        "--car-slot", car_slot,
        "--out", str(out_path),
        "--force",
    ]
    if car_model:
        cmd += ["--car-model", car_model]
    print(f"[run_local] 生成配置: {' '.join(cmd)}")
    return subprocess.call(cmd)


def _find_webots(explicit: Optional[str]) -> Optional[str]:
    """按优先级查找 Webots 可执行文件路径。

    查找顺序：
      1. 命令行 --webots 显式指定
      2. $WEBOTS_HOME（多种布局：Windows msys64 / Linux root / macOS .app 内）
      3. $PATH
      4. 平台常见默认安装路径（Windows / Linux / macOS）
    """
    # 1. 命令行参数显式指定
    if explicit:
        if pathlib.Path(explicit).is_file():
            return explicit
        print(f"[run_local][warn] --webots 指定的路径不存在: {explicit}", file=sys.stderr)

    # 2. 环境变量
    env = os.environ.get("WEBOTS_HOME")
    if env:
        env_path = pathlib.Path(env)
        candidates: list[pathlib.Path] = []
        if sys.platform == "win32":
            candidates += [
                env_path / "msys64/mingw64/bin/webotsw.exe",
                env_path / "msys64/mingw64/bin/webots.exe",
                env_path / "webotsw.exe",
                env_path / "webots.exe",
            ]
        elif sys.platform == "darwin":
            candidates += [
                env_path / "Contents/MacOS/webots",
                env_path / "webots",
            ]
        else:  # linux
            candidates += [env_path / "webots", env_path / "bin/webots"]
        # 兼容把 WEBOTS_HOME 直接指向含 webots 可执行文件的 bin 目录
        for name in ("webots", "webotsw.exe", "webots.exe"):
            candidates.append(env_path / name)
        for c in candidates:
            if c.is_file():
                return str(c)

    # 3. PATH 里查找
    for name in ("webots", "webotsw", "webots.exe", "webotsw.exe"):
        found = shutil.which(name)
        if found:
            return found

    # 4. 各平台常见默认路径
    defaults_common: list[str] = []

    if sys.platform == "win32":
        # Windows：扫描所有可用盘符下的常见安装目录
        #   （用户常把 Webots 装在 D:/E:/F: 等非系统盘）
        win_rel_paths = [
            r"Webots\msys64\mingw64\bin\webotsw.exe",
            r"Webots\msys64\mingw64\bin\webots.exe",
            r"Program Files\Webots\msys64\mingw64\bin\webotsw.exe",
            r"Program Files\Webots\msys64\mingw64\bin\webots.exe",
            r"Program Files (x86)\Webots\msys64\mingw64\bin\webotsw.exe",
            r"Program Files (x86)\Webots\msys64\mingw64\bin\webots.exe",
        ]
        drives = [f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                  if pathlib.Path(f"{d}:\\").exists()]
        for drive in drives:
            for rel in win_rel_paths:
                defaults_common.append(drive + rel)
    else:
        defaults_common += [
            # Linux
            "/usr/local/webots/webots",
            "/usr/bin/webots",
            "/snap/bin/webots",
            "/opt/webots/webots",
            # macOS
            "/Applications/Webots.app/Contents/MacOS/webots",
            "/Applications/Webots.app/webots",
            os.path.expanduser("~/Applications/Webots.app/Contents/MacOS/webots"),
        ]

    for d in defaults_common:
        if pathlib.Path(d).is_file():
            return d

    return None


def _launch_webots(
    webots_exe: str,
    world: pathlib.Path,
    config_path: pathlib.Path,
    fast: bool,
    minimized: bool,
    batch: bool,
) -> int:
    """启动 Webots，通过 RACE_CONFIG_PATH 环境变量把配置传给 car_controller。"""
    env = os.environ.copy()
    env["RACE_CONFIG_PATH"] = str(config_path.resolve())

    cmd = [webots_exe]
    if fast:
        cmd.append("--mode=fast")
    if minimized:
        cmd.append("--minimize")
    if batch:
        cmd.append("--batch")
    cmd.append(str(world.resolve()))

    print(f"[run_local] 启动 Webots: {' '.join(cmd)}")
    print(f"[run_local] RACE_CONFIG_PATH = {env['RACE_CONFIG_PATH']}")
    try:
        return subprocess.call(cmd, env=env)
    except FileNotFoundError as e:
        print(f"[run_local][error] 无法启动 Webots: {e}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AI Racer 本地一键运行：校验 + 生成配置 + 启动 Webots",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # --list-worlds 不需要 --code-path，因此 required 在 main() 里手动校验
    p.add_argument("--code-path",
                   help="team_controller.py 的路径（--list-worlds 时可省略；"
                        "与 --car 互斥，两者只选其一）")
    p.add_argument("--team-id", default="local_team",
                   help="队伍 ID（默认 local_team；仅 --code-path 单车模式生效）")
    p.add_argument("--car-slot", default="car_1",
                   help="赛道中的车位名（car_1 / car_2 / …；用 --list-worlds "
                        "查看每个赛道的车位与对应车型；仅 --code-path 单车模式生效）")
    p.add_argument(
        "--car",
        action="append",
        default=[],
        metavar="PATH:SLOT:TEAM",
        help="多车模式：添加一辆车，格式 controller_path:slot:team（可重复指定，"
             "每次指定一辆）。与 --code-path 互斥。",
    )
    p.add_argument("--world", default=DEFAULT_WORLD_KEY,
                   help=f"赛道：短名（{'/'.join(WORLDS)}）、"
                        f".wbt 文件名、或完整路径。默认 {DEFAULT_WORLD_KEY}。")
    p.add_argument("--list-worlds", action="store_true",
                   help="列出所有可用赛道与车型后退出")
    try:
        _cfg_display = DEFAULT_CONFIG.relative_to(SDK_DIR.parent)
    except ValueError:
        try:
            _cfg_display = DEFAULT_CONFIG.relative_to(SDK_DIR)
            _cfg_display = pathlib.Path("sdk") / _cfg_display
        except ValueError:
            _cfg_display = DEFAULT_CONFIG
    p.add_argument("--config-out", default=str(DEFAULT_CONFIG),
                   help=f"生成的 race_config.json 路径（默认 {_cfg_display}）")
    p.add_argument("--rules", default=None,
                   help="validator 规则 YAML 路径（默认 sdk/rules.yaml）")
    p.add_argument("--webots", default=None,
                   help="Webots 可执行文件路径（缺省自动探测）")
    p.add_argument("--fast", action="store_true",
                   help="使用 --mode=fast 启动 Webots（无渲染，跑得快）")
    p.add_argument("--minimize", action="store_true",
                   help="最小化 Webots 窗口")
    p.add_argument("--batch", action="store_true",
                   help="以 --batch 方式启动（无弹窗）")
    p.add_argument("--validate-only", action="store_true",
                   help="仅校验代码，不启动 Webots")
    p.add_argument("--skip-validate", action="store_true",
                   help="跳过校验，直接生成配置并启动")
    return p


def main() -> int:
    args = build_parser().parse_args()

    # --- --list-worlds 捷径：直接打印后退出 ---
    if args.list_worlds:
        print(format_catalog())
        return 0

    # --- 互斥检查：--code-path 与 --car 不能同时使用 ---
    if args.code_path and args.car:
        print("[run_local][error] --code-path 与 --car 不能同时使用，请选择其中一种模式。",
              file=sys.stderr)
        return 1

    # --- 解析车辆列表（统一成内部格式） ---
    # 内部格式：list of {car_id, slot, team, controller_path}
    if args.car:
        # 多车模式：解析 --car PATH:SLOT:TEAM
        cars: list[dict] = []
        seen_slots: set[str] = set()
        for i, spec in enumerate(args.car):
            parts = spec.split(":", 2)
            if len(parts) != 3:
                print(
                    f"[run_local][error] --car 格式错误: {spec!r}。"
                    "期望格式：controller_path:slot:team",
                    file=sys.stderr,
                )
                return 1
            ctrl_path_str, slot, team = (s.strip() for s in parts)
            if not all([ctrl_path_str, slot, team]):
                print(
                    f"[run_local][error] --car 参数中 controller_path/slot/team 不能为空: {spec!r}",
                    file=sys.stderr,
                )
                return 1
            if slot in seen_slots:
                print(
                    f"[run_local][error] slot 冲突：{slot!r} 被多辆车使用。"
                    "每辆车必须分配唯一车位。",
                    file=sys.stderr,
                )
                return 1
            seen_slots.add(slot)
            ctrl_path = pathlib.Path(ctrl_path_str).expanduser().resolve()
            if not ctrl_path.is_file():
                print(f"[run_local][error] 控制器文件不存在: {ctrl_path}", file=sys.stderr)
                return 1
            cars.append({
                "car_id": f"car_{i}",
                "slot": slot,
                "team": team,
                "controller_path": str(ctrl_path),
            })
        multi_car_mode = True
    elif args.code_path:
        # 单车兼容模式：--code-path 包装为长度为 1 的车辆列表
        code_path = pathlib.Path(args.code_path).expanduser().resolve()
        if not code_path.is_file():
            print(f"[run_local][error] 代码文件不存在: {code_path}", file=sys.stderr)
            return 1
        cars = [{
            "car_id": "car_0",
            "slot": args.car_slot,
            "team": args.team_id,
            "controller_path": str(code_path),
        }]
        multi_car_mode = False
    else:
        print("[run_local][error] 必须通过 --code-path（单车）或 --car（多车）指定控制器文件 "
              "（或改用 --list-worlds 查看赛道目录）", file=sys.stderr)
        return 1

    # --- 解析 --world：短名 / 文件名 / 路径 ---
    world_entry = resolve_world(args.world)
    world_path = world_entry.path.resolve() if world_entry.path.is_absolute() \
        else pathlib.Path(world_entry.path).expanduser().resolve()

    if not args.validate_only and not world_path.is_file():
        print(f"[run_local][error] 世界文件不存在: {world_path}\n"
              f"    提示：用 `python sdk/run_local.py --list-worlds` 查看可用赛道。",
              file=sys.stderr)
        return 1

    # --- 校验 slot 是否存在于该赛道（仅对已登记赛道做校验；自定义路径跳过） ---
    car_model_name: Optional[str] = None
    if not multi_car_mode and world_entry.cars:
        single_slot = cars[0]["slot"]
        if single_slot not in world_entry.cars:
            print(
                f"[run_local][error] 车位 {single_slot!r} 不在赛道 "
                f"{world_entry.key!r} 中。可用车位：{', '.join(world_entry.slots)}",
                file=sys.stderr,
            )
            return 1
        car_entry = world_entry.cars[single_slot]
        car_model_name = car_entry.proto
        print(f"[run_local] 赛道: {world_entry.title}")
        print(f"[run_local] 车位: {single_slot} -> {car_entry.label()}")
    elif multi_car_mode:
        print(f"[run_local] 赛道: {world_entry.title}")
        print(f"[run_local] 多车模式：{len(cars)} 辆车")
        for car in cars:
            print(f"[run_local]   {car['car_id']}: slot={car['slot']}  "
                  f"team={car['team']}  code={car['controller_path']}")

    rules_path: Optional[pathlib.Path] = None
    if args.rules:
        rules_path = pathlib.Path(args.rules).expanduser().resolve()
    elif (SDK_DIR / "rules.yaml").is_file():
        rules_path = SDK_DIR / "rules.yaml"

    # --- Step 1: 校验（对每辆车依次校验） ---
    if not args.skip_validate:
        rc = _validate_cars(cars, rules_path)
        if rc != 0:
            print("[run_local] 校验未通过，终止。", file=sys.stderr)
            return 2

    if args.validate_only:
        print("[run_local] --validate-only 模式，结束。")
        return 0

    # --- Step 2: 生成 race_config.json ---
    config_path = pathlib.Path(args.config_out).expanduser().resolve()
    # 确保 .local/ 目录存在
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if multi_car_mode:
        rc = _make_config_multi(cars, world_entry.key, config_path)
    else:
        rc = _make_config(
            pathlib.Path(cars[0]["controller_path"]),
            cars[0]["team"],
            cars[0]["slot"],
            config_path,
            car_model=car_model_name,
        )
    if rc != 0:
        print("[run_local] 生成 race_config 失败。", file=sys.stderr)
        return 1

    # --- Step 3: 启动 Webots ---
    webots_exe = _find_webots(args.webots)
    if webots_exe is None:
        print(
            "[run_local][error] 未能找到 Webots 可执行文件。\n"
            "    请使用 --webots 显式指定，或设置 WEBOTS_HOME 环境变量。",
            file=sys.stderr,
        )
        return 1

    rc = _launch_webots(
        webots_exe=webots_exe,
        world=world_path,
        config_path=config_path,
        fast=args.fast,
        minimized=args.minimize,
        batch=args.batch,
    )
    if rc != 0:
        print(f"[run_local] Webots 非 0 退出（{rc}）", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

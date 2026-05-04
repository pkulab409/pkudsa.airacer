"""run_local.py — AI Racer 本地一键启动脚本

把"校验代码 → 生成 race_config.json → 启动 Webots"三步封装成一条命令，
降低学生首次上手门槛。

典型用法
--------
# 最小用法：使用默认模板 + 默认世界
python sdk/run_local.py --code-path sdk/example_controller.py

# 指定队伍 ID / 车位 / 世界文件
python sdk/run_local.py \
    --code-path my_controller.py \
    --team-id my_team \
    --car-slot car_1 \
    --world simnode/webots/worlds/airacer.wbt

# 只跑校验，不启动 Webots（CI / 提交前自检）
python sdk/run_local.py --code-path my_controller.py --validate-only

# 不做校验直接跑（已知代码通过校验时使用）
python sdk/run_local.py --code-path my_controller.py --skip-validate

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
REPO_ROOT = SDK_DIR.parent

DEFAULT_WORLD = REPO_ROOT / "simnode" / "webots" / "worlds" / "airacer.wbt"
# 生成的临时 race_config 放到仓库根 .local/，避免污染 SDK 目录（便于打包分发）
DEFAULT_CONFIG = REPO_ROOT / ".local" / "race_config.json"


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


def _make_config(
    code_path: pathlib.Path,
    team_id: str,
    car_slot: str,
    out_path: pathlib.Path,
) -> int:
    """调用 make_local_config.py 生成 race_config.json。"""
    cmd = [
        sys.executable, str(SDK_DIR / "make_local_config.py"),
        "--code-path", str(code_path),
        "--team-id", team_id,
        "--car-slot", car_slot,
        "--out", str(out_path),
        "--force",
    ]
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
    defaults_common = [
        # Windows
        r"C:\Program Files\Webots\msys64\mingw64\bin\webotsw.exe",
        r"C:\Program Files\Webots\msys64\mingw64\bin\webots.exe",
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
    p.add_argument("--code-path", required=True,
                   help="team_controller.py 的路径")
    p.add_argument("--team-id", default="local_team",
                   help="队伍 ID（默认 local_team）")
    p.add_argument("--car-slot", default="car_1",
                   help="世界文件中的 Robot 节点名（默认 car_1，对应 airacer.wbt）")
    p.add_argument("--world", default=str(DEFAULT_WORLD),
                   help=f"Webots 世界文件路径（默认 {DEFAULT_WORLD.relative_to(REPO_ROOT)}）")
    try:
        _cfg_display = DEFAULT_CONFIG.relative_to(REPO_ROOT)
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

    code_path = pathlib.Path(args.code_path).expanduser().resolve()
    if not code_path.is_file():
        print(f"[run_local][error] 代码文件不存在: {code_path}", file=sys.stderr)
        return 1

    world_path = pathlib.Path(args.world).expanduser().resolve()
    if not args.validate_only and not world_path.is_file():
        print(f"[run_local][error] 世界文件不存在: {world_path}", file=sys.stderr)
        return 1

    rules_path: Optional[pathlib.Path] = None
    if args.rules:
        rules_path = pathlib.Path(args.rules).expanduser().resolve()
    elif (SDK_DIR / "rules.yaml").is_file():
        rules_path = SDK_DIR / "rules.yaml"

    # --- Step 1: 校验 ---
    if not args.skip_validate:
        rc = _run_validator(code_path, rules_path)
        if rc != 0:
            print("[run_local] 校验未通过，终止。", file=sys.stderr)
            return 2

    if args.validate_only:
        print("[run_local] --validate-only 模式，结束。")
        return 0

    # --- Step 2: 生成 race_config.json ---
    config_path = pathlib.Path(args.config_out).expanduser().resolve()
    rc = _make_config(code_path, args.team_id, args.car_slot, config_path)
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

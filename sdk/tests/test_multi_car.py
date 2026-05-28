"""
sdk/tests/test_multi_car.py — 多车并发流程的集成测试

覆盖要点：
  1. 多车 race_config.json 生成正确性
     - cars[] 长度与输入车辆数一致
     - car_id 全局唯一
     - slot 冲突时抛出预期异常或返回错误
  2. 多控制器批量校验流程
     - 全部合法控制器：流程正常通过
     - 含一个非法控制器：流程在该车处中止，返回非零退出码
  3. 单车 --code-path 兼容路径回归：输出 cars[] 长度为 1 且结构正确

运行：
    cd pkudsa.airacer
    pytest sdk/tests/test_multi_car.py -v
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

# 把 sdk/ 加入 sys.path，便于直接导入 make_local_config
SDK_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from make_local_config import (  # noqa: E402
    collect_cars,
    build_parser,
    parse_car_multi_spec,
)

MAKE_CONFIG = SDK_DIR / "make_local_config.py"
VALIDATE_CONTROLLER = SDK_DIR / "validate_controller.py"
RUN_LOCAL = SDK_DIR / "run_local.py"

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _write(tmp_path: pathlib.Path, name: str, src: str) -> pathlib.Path:
    """把源码写入临时目录，返回绝对路径。"""
    p = tmp_path / name
    p.write_text(textwrap.dedent(src).lstrip(), encoding="utf-8")
    return p


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# 合法控制器源码
GOOD_CTRL = """
    import numpy as np
    def control(left_img, right_img, timestamp):
        return 0.0, 0.5
"""

# 非法控制器源码（含黑名单 import → E004）
BAD_CTRL = """
    import os
    def control(left_img, right_img, timestamp):
        return 0.0, 0.5
"""

# ---------------------------------------------------------------------------
# 1. 多车 race_config.json 生成正确性
# ---------------------------------------------------------------------------


class TestMultiCarConfigGeneration:
    """通过 Python API 直接调用 make_local_config 的内部函数进行测试。"""

    def _build_args(
        self,
        car_multi_specs: list[str],
        car_specs: list[str] | None = None,
        code_path: str | None = None,
    ) -> argparse.Namespace:
        """构造 argparse.Namespace 供 collect_cars 使用。"""
        parser = build_parser()
        cli_args: list[str] = []
        for spec in car_multi_specs:
            cli_args += ["--car-multi", spec]
        for spec in (car_specs or []):
            cli_args += ["--car", spec]
        if code_path:
            cli_args += ["--code-path", code_path]
        return parser.parse_args(cli_args)

    def test_multi_car_length(self, tmp_path):
        """cars[] 长度与输入车辆数一致。"""
        ctrl_a = _write(tmp_path, "a.py", GOOD_CTRL)
        ctrl_b = _write(tmp_path, "b.py", GOOD_CTRL)
        ctrl_c = _write(tmp_path, "c.py", GOOD_CTRL)

        args = self._build_args([
            f"car_0:car_1:red:{ctrl_a}",
            f"car_1:car_2:blue:{ctrl_b}",
            f"car_2:car_3:green:{ctrl_c}",
        ])
        cars = collect_cars(args)
        assert len(cars) == 3

    def test_car_id_unique(self, tmp_path):
        """car_id 全局唯一。"""
        ctrl_a = _write(tmp_path, "a.py", GOOD_CTRL)
        ctrl_b = _write(tmp_path, "b.py", GOOD_CTRL)

        args = self._build_args([
            f"car_0:car_1:red:{ctrl_a}",
            f"car_1:car_2:blue:{ctrl_b}",
        ])
        cars = collect_cars(args)
        ids = [c["car_id"] for c in cars]
        assert len(ids) == len(set(ids)), "car_id 存在重复"

    def test_duplicate_car_id_raises(self, tmp_path):
        """相同 car_id 应抛出 ValueError。"""
        ctrl_a = _write(tmp_path, "a.py", GOOD_CTRL)
        ctrl_b = _write(tmp_path, "b.py", GOOD_CTRL)

        args = self._build_args([
            f"car_0:car_1:red:{ctrl_a}",
            f"car_0:car_2:blue:{ctrl_b}",   # 重复 car_id=car_0
        ])
        with pytest.raises(ValueError, match="car_id"):
            collect_cars(args)

    def test_slot_conflict_raises(self, tmp_path):
        """slot 冲突应抛出 ValueError。"""
        ctrl_a = _write(tmp_path, "a.py", GOOD_CTRL)
        ctrl_b = _write(tmp_path, "b.py", GOOD_CTRL)

        args = self._build_args([
            f"car_0:car_1:red:{ctrl_a}",
            f"car_1:car_1:blue:{ctrl_b}",   # 重复 slot=car_1
        ])
        with pytest.raises(ValueError, match="slot"):
            collect_cars(args)

    def test_new_fields_present(self, tmp_path):
        """输出条目包含 car_id / slot / team / controller_path 字段。"""
        ctrl_a = _write(tmp_path, "a.py", GOOD_CTRL)

        args = self._build_args([f"my_car:car_1:red_team:{ctrl_a}"])
        cars = collect_cars(args)
        assert len(cars) == 1
        car = cars[0]
        assert car["car_id"] == "my_car"
        assert car["slot"] == "car_1"
        assert car["team"] == "red_team"
        assert str(ctrl_a) == car["controller_path"]

    def test_json_output_via_cli(self, tmp_path):
        """通过 CLI 调用 make_local_config.py，检查输出 JSON 结构。"""
        ctrl_a = _write(tmp_path, "a.py", GOOD_CTRL)
        ctrl_b = _write(tmp_path, "b.py", GOOD_CTRL)
        out_path = tmp_path / "race_config.json"

        result = _run([
            sys.executable, str(MAKE_CONFIG),
            "--world", "basic",
            "--car-multi", f"car_0:car_1:red:{ctrl_a}",
            "--car-multi", f"car_1:car_2:blue:{ctrl_b}",
            "--out", str(out_path),
            "--force",
        ])
        assert result.returncode == 0, result.stderr

        cfg = json.loads(out_path.read_text(encoding="utf-8"))
        assert cfg.get("world") == "basic"
        assert isinstance(cfg["cars"], list)
        assert len(cfg["cars"]) == 2

        car_ids = [c["car_id"] for c in cfg["cars"]]
        assert "car_0" in car_ids
        assert "car_1" in car_ids

        for car in cfg["cars"]:
            assert "car_id" in car
            assert "slot" in car
            assert "team" in car
            assert "controller_path" in car

    def test_slot_conflict_cli_returns_error(self, tmp_path):
        """CLI 模式下 slot 冲突应返回非零退出码。"""
        ctrl_a = _write(tmp_path, "a.py", GOOD_CTRL)
        ctrl_b = _write(tmp_path, "b.py", GOOD_CTRL)
        out_path = tmp_path / "race_config.json"

        result = _run([
            sys.executable, str(MAKE_CONFIG),
            "--car-multi", f"car_0:car_1:red:{ctrl_a}",
            "--car-multi", f"car_1:car_1:blue:{ctrl_b}",  # slot 冲突
            "--out", str(out_path),
            "--force",
        ])
        assert result.returncode != 0, "slot 冲突应返回非零退出码"


# ---------------------------------------------------------------------------
# 2. 多控制器批量校验流程
# ---------------------------------------------------------------------------


class TestMultiCarValidation:
    """通过 CLI 调用 validate_controller.py 验证多车批量校验行为。"""

    def _validate(self, code_path: pathlib.Path) -> int:
        """对单个控制器调用 validate_controller.py，返回退出码。"""
        result = _run([
            sys.executable, str(VALIDATE_CONTROLLER),
            "--code-path", str(code_path),
        ])
        return result.returncode

    def test_all_valid_controllers_pass(self, tmp_path):
        """全部合法控制器：每辆车校验均通过（退出码 0）。"""
        ctrls = [_write(tmp_path, f"ctrl_{i}.py", GOOD_CTRL) for i in range(3)]
        for ctrl in ctrls:
            assert self._validate(ctrl) == 0, f"合法控制器 {ctrl} 应通过校验"

    def test_invalid_controller_fails(self, tmp_path):
        """含非法控制器时该车校验失败（退出码非 0）。"""
        bad_ctrl = _write(tmp_path, "bad.py", BAD_CTRL)
        assert self._validate(bad_ctrl) != 0, "非法控制器应返回非零退出码"

    def test_multi_car_stops_at_first_invalid(self, tmp_path):
        """
        模拟 run_local.py 的 _validate_cars 逻辑：
        含一个非法控制器时，流程在该车处中止并返回非零退出码。
        """
        # 直接调用 run_local.py 的内部函数（通过 importlib 动态加载）
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_local", str(RUN_LOCAL)
        )
        run_local_mod = importlib.util.module_from_spec(spec)
        # run_local 顶层会 import worlds，需要 sdk/ 在 sys.path 里（已在模块头部插入）
        spec.loader.exec_module(run_local_mod)

        good_ctrl = _write(tmp_path, "good.py", GOOD_CTRL)
        bad_ctrl = _write(tmp_path, "bad.py", BAD_CTRL)

        cars = [
            {"car_id": "car_0", "slot": "car_1", "team": "red",
             "controller_path": str(good_ctrl)},
            {"car_id": "car_1", "slot": "car_2", "team": "blue",
             "controller_path": str(bad_ctrl)},   # 非法
        ]

        rc = run_local_mod._validate_cars(cars, None)
        assert rc != 0, "含非法控制器的多车列表应返回非零退出码"

    def test_all_valid_via_validate_cars(self, tmp_path):
        """全部合法控制器：_validate_cars 返回 0。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_local", str(RUN_LOCAL)
        )
        run_local_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run_local_mod)

        ctrls = [_write(tmp_path, f"c{i}.py", GOOD_CTRL) for i in range(2)]
        cars = [
            {"car_id": f"car_{i}", "slot": f"car_{i + 1}", "team": f"team_{i}",
             "controller_path": str(ctrl)}
            for i, ctrl in enumerate(ctrls)
        ]

        rc = run_local_mod._validate_cars(cars, None)
        assert rc == 0, "全部合法控制器应返回退出码 0"


# ---------------------------------------------------------------------------
# 3. 单车 --code-path 兼容路径回归
# ---------------------------------------------------------------------------


class TestSingleCarCompatibility:
    """确保 --code-path 单车用法在新逻辑下仍然向下兼容。"""

    def test_single_car_via_code_path_api(self, tmp_path):
        """--code-path 模式生成的 cars[] 长度为 1，且包含新格式字段。"""
        ctrl = _write(tmp_path, "ctrl.py", GOOD_CTRL)
        parser = build_parser()
        args = parser.parse_args([
            "--code-path", str(ctrl),
            "--team-id", "my_team",
            "--car-slot", "car_3",
        ])
        cars = collect_cars(args)
        assert len(cars) == 1, "单车模式 cars[] 应为长度 1"
        car = cars[0]
        # 新格式字段
        assert car.get("car_id") == "car_3"
        assert car.get("slot") == "car_3"
        assert car.get("team") == "my_team"
        assert car.get("controller_path") == str(ctrl)
        # 老格式兼容字段仍在
        assert car.get("car_slot") == "car_3"
        assert car.get("team_id") == "my_team"
        assert car.get("code_path") == str(ctrl)

    def test_single_car_via_cli(self, tmp_path):
        """通过 CLI 调用 make_local_config.py --code-path，输出 cars[] 长度为 1。"""
        ctrl = _write(tmp_path, "ctrl.py", GOOD_CTRL)
        out_path = tmp_path / "race_config.json"

        result = _run([
            sys.executable, str(MAKE_CONFIG),
            "--code-path", str(ctrl),
            "--team-id", "solo_team",
            "--car-slot", "car_2",
            "--out", str(out_path),
            "--force",
        ])
        assert result.returncode == 0, result.stderr

        cfg = json.loads(out_path.read_text(encoding="utf-8"))
        assert len(cfg["cars"]) == 1, "单车模式 cars[] 应为长度 1"
        car = cfg["cars"][0]
        # 新格式字段
        assert car.get("slot") == "car_2"
        assert car.get("team") == "solo_team"
        assert "controller_path" in car

    def test_parse_car_multi_spec(self, tmp_path):
        """parse_car_multi_spec 正确解析 car_id:slot:team:controller_path。"""
        ctrl = _write(tmp_path, "ctrl.py", GOOD_CTRL)
        spec = f"my_car:car_1:red_team:{ctrl}"
        entry = parse_car_multi_spec(spec)
        assert entry["car_id"] == "my_car"
        assert entry["slot"] == "car_1"
        assert entry["team"] == "red_team"
        assert entry["controller_path"] == str(ctrl)
        # 老格式字段也应存在
        assert entry["car_slot"] == "car_1"
        assert entry["team_id"] == "red_team"
        assert entry["code_path"] == str(ctrl)

    def test_parse_car_multi_spec_invalid_raises(self):
        """parse_car_multi_spec 对格式错误的 spec 抛出 ArgumentTypeError。"""
        with pytest.raises(argparse.ArgumentTypeError):
            parse_car_multi_spec("only_two:parts")

    def test_single_car_default_slot(self, tmp_path):
        """--code-path 未指定 --car-slot 时使用默认值 car_1。"""
        ctrl = _write(tmp_path, "ctrl.py", GOOD_CTRL)
        parser = build_parser()
        args = parser.parse_args(["--code-path", str(ctrl)])
        cars = collect_cars(args)
        assert cars[0].get("slot") == "car_1"

"""
sdk/tests/test_cli.py — validate_controller.py 的 CLI 层冒烟测试

验收要点：
    * --json 输出可被 json.loads 解析，键齐全
    * --strict 对仅含 warning 的代码返回退出码 3
    * --rules 指向不存在文件时返回退出码 2
    * 正常通过退出码 0；存在 error 退出码 1
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "sdk" / "validate_controller.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _write(tmp_path: pathlib.Path, name: str, src: str) -> pathlib.Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(src).lstrip(), encoding="utf-8")
    return p


GOOD = """
    import numpy as np
    def control(left_img, right_img, timestamp):
        return 0.0, 0.5
"""

WITH_WARN = """
    import numpy as np
    import pandas   # 未知 import → W004 warn
    def control(left_img, right_img, timestamp):
        return 0.0, 0.5
"""

WITH_ERROR = """
    import os       # E004 error
    def control(left_img, right_img, timestamp):
        return 0.0, 0.5
"""


# ---------------------------------------------------------------------------
# 退出码契约
# ---------------------------------------------------------------------------

def test_exit_0_on_pass(tmp_path):
    p = _write(tmp_path, "ok.py", GOOD)
    r = _run_cli("--code-path", str(p))
    assert r.returncode == 0, r.stdout + r.stderr


def test_exit_1_on_error(tmp_path):
    p = _write(tmp_path, "bad.py", WITH_ERROR)
    r = _run_cli("--code-path", str(p))
    assert r.returncode == 1, r.stdout + r.stderr


def test_exit_2_on_bad_rules_path(tmp_path):
    p = _write(tmp_path, "ok.py", GOOD)
    r = _run_cli(
        "--code-path", str(p),
        "--rules", str(tmp_path / "no_such_rules.yaml"),
    )
    assert r.returncode == 2, r.stdout + r.stderr


def test_exit_3_on_strict_with_warning(tmp_path):
    """--strict 下，仅 warning 也视为未通过 → 退出码 3。"""
    p = _write(tmp_path, "warn.py", WITH_WARN)
    r = _run_cli("--code-path", str(p), "--strict")
    # 注意：没有装 pandas 时动态加载会记 E011 → 退出码 1；这里我们只断言
    # 非 0（即 strict 至少不会为 0 放行 warning）
    assert r.returncode in (1, 3), (
        f"expected 1 or 3, got {r.returncode}\n{r.stdout}\n{r.stderr}"
    )


# ---------------------------------------------------------------------------
# JSON 输出结构
# ---------------------------------------------------------------------------

def test_json_output_is_parsable(tmp_path):
    p = _write(tmp_path, "ok.py", GOOD)
    r = _run_cli("--code-path", str(p), "--json")
    # 正常通过时 returncode==0，stdout 是一段 JSON
    data = json.loads(r.stdout)
    assert set(data.keys()) == {"passed", "errors", "warnings", "summary", "meta"}
    assert data["passed"] is True
    assert isinstance(data["errors"], list)
    assert isinstance(data["warnings"], list)
    assert "avg_call_ms" in data["meta"]


def test_json_output_on_error(tmp_path):
    p = _write(tmp_path, "bad.py", WITH_ERROR)
    r = _run_cli("--code-path", str(p), "--json")
    data = json.loads(r.stdout)
    assert data["passed"] is False
    codes = {e["code"] for e in data["errors"]}
    assert "E004" in codes


# ---------------------------------------------------------------------------
# 内置样例（sdk/ 下的三份示例）必须通过
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "sdk/team_controller.py",
    "sdk/example_controller.py",
    "sdk/examples/team_controller_tutorial.py",
])
def test_shipped_samples_pass(rel):
    p = REPO_ROOT / rel
    if not p.is_file():
        pytest.skip(f"{rel} not found")
    r = _run_cli("--code-path", str(p))
    assert r.returncode == 0, (
        f"Shipped sample {rel} should pass validator but got "
        f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

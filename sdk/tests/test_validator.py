"""
sdk/tests/test_validator.py — sdk/validate_controller.py 的 pytest 套件

覆盖每一条规则的至少一个正样本 + 一个反样本：

  R1  文件大小超限           — E001
  R2  语法错误               — E003
  R3  黑名单 import          — E004
  R4  黑名单 from-import     — E004
  R5  未知 import（warn）    — W004
  R6  白名单 import（正）    — 通过
  R7  禁用内置 open()        — E006
  R8  禁用内置 eval()        — E006
  R9a 逃逸属性访问           — E007（error，阻塞）
  R9b 可疑属性访问           — W007（warn，不阻塞通过）
  R10 缺少 control 函数      — E008
  R11 control 签名错误       — W008（warn）
  R12 control 返回非 tuple   — E012
  R13 control 返回值越界     — W013（warn）
  R14 control 首调抛异常     — W011（warn，线上有 try/except）

运行：
    cd pkudsa.airacer
    pytest sdk/tests/test_validator.py -v
"""

from __future__ import annotations

import pathlib
import sys
import textwrap

import pytest

# 位置：sdk/tests/test_validator.py
# 把 sdk/ 目录加入 sys.path，然后直接 `import validate_controller`。
# 这样不依赖仓库根当包根，也不强制 `sdk` 变 Python 包。
SDK_DIR = pathlib.Path(__file__).resolve().parent.parent   # -> sdk/
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from validate_controller import (  # noqa: E402
    Validator,
    ValidationReport,
    DEFAULT_RULES,
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _write(tmp_path: pathlib.Path, name: str, src: str) -> pathlib.Path:
    """把源码写入临时目录，返回路径。"""
    p = tmp_path / name
    p.write_text(textwrap.dedent(src).lstrip(), encoding="utf-8")
    return p


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def _run(path: pathlib.Path, rules=None) -> ValidationReport:
    return Validator(rules or DEFAULT_RULES).check(path)


GOOD_SRC = """
    import numpy as np

    def control(left_img, right_img, timestamp):
        return 0.0, 0.5
"""


# ---------------------------------------------------------------------------
# 正样本
# ---------------------------------------------------------------------------

class TestPositive:
    def test_minimal_template_passes(self, tmp_path):
        """R6 白名单 import + 合法返回 → passed=True。"""
        p = _write(tmp_path, "ok.py", GOOD_SRC)
        rep = _run(p)
        assert rep.passed, f"expected passed, got: {rep.errors}"
        assert rep.errors == []

    def test_allow_list_imports_only(self, tmp_path):
        """typing / math / collections / heapq / functools / itertools 均允许。"""
        src = """
            import math
            import heapq
            from collections import deque
            from functools import lru_cache
            from itertools import count
            from typing import Tuple
            import numpy as np

            def control(left_img, right_img, timestamp):
                _ = deque(maxlen=3)
                return 0.0, 0.5
        """
        p = _write(tmp_path, "allow.py", src)
        rep = _run(p)
        assert rep.passed, rep.errors


# ---------------------------------------------------------------------------
# R1 文件大小
# ---------------------------------------------------------------------------

class TestFileSize:
    def test_oversize_rejected(self, tmp_path):
        rules = {**DEFAULT_RULES,
                 "file": {"max_size_kb": 1, "encoding": "utf-8"}}
        # 写 3KB 的注释
        bulk = "# " + ("x" * 80 + "\n") * 50  # > 1KB
        src = bulk + GOOD_SRC
        p = _write(tmp_path, "big.py", src)
        rep = _run(p, rules=rules)
        assert "E001" in _codes(rep.errors)
        assert not rep.passed


# ---------------------------------------------------------------------------
# R2 语法
# ---------------------------------------------------------------------------

class TestSyntax:
    def test_syntax_error_rejected(self, tmp_path):
        src = "def control(a, b, c)\n    return 0, 0\n"   # 缺冒号
        p = _write(tmp_path, "bad.py", src)
        rep = _run(p)
        assert "E003" in _codes(rep.errors)
        assert not rep.passed


# ---------------------------------------------------------------------------
# R3-R4 黑名单 import
# ---------------------------------------------------------------------------

class TestImports:
    def test_deny_import_os(self, tmp_path):
        src = """
            import os
            def control(a, b, c):
                return 0.0, 0.5
        """
        p = _write(tmp_path, "os_imp.py", src)
        rep = _run(p)
        codes = _codes(rep.errors)
        assert "E004" in codes
        assert any("os" in f.message for f in rep.errors)
        assert not rep.passed

    def test_deny_from_import_subprocess(self, tmp_path):
        src = """
            from subprocess import Popen
            def control(a, b, c):
                return 0.0, 0.5
        """
        p = _write(tmp_path, "sp.py", src)
        rep = _run(p)
        assert "E004" in _codes(rep.errors)

    def test_deny_import_socket(self, tmp_path):
        src = """
            import socket
            def control(a, b, c):
                return 0.0, 0.5
        """
        p = _write(tmp_path, "sk.py", src)
        rep = _run(p)
        assert "E004" in _codes(rep.errors)

    def test_warn_on_unknown_import(self, tmp_path):
        """R5：非黑非白 → warn，但 passed=True。"""
        src = """
            import pandas       # 既非黑也非白
            def control(a, b, c):
                return 0.0, 0.5
        """
        p = _write(tmp_path, "unknown.py", src)
        rep = _run(p)
        assert "W004" in _codes(rep.warnings)
        # passed 取决于动态加载；pandas 未装时会触发 E011 module load 失败 —— 放宽断言
        # 仅确认 warning 被记录
        assert any("pandas" in f.message for f in rep.warnings)

    def test_relative_import_rejected(self, tmp_path):
        src = """
            from . import sibling
            def control(a, b, c):
                return 0.0, 0.5
        """
        p = _write(tmp_path, "rel.py", src)
        rep = _run(p)
        assert "E005" in _codes(rep.errors)


# ---------------------------------------------------------------------------
# R7-R8 禁用内置
# ---------------------------------------------------------------------------

class TestBuiltins:
    def test_deny_open(self, tmp_path):
        src = """
            def control(a, b, c):
                f = open("x.txt")
                return 0.0, 0.5
        """
        p = _write(tmp_path, "op.py", src)
        rep = _run(p)
        assert "E006" in _codes(rep.errors)
        assert any("open" in f.message for f in rep.errors)

    def test_deny_eval(self, tmp_path):
        src = """
            def control(a, b, c):
                eval("1+1")
                return 0.0, 0.5
        """
        p = _write(tmp_path, "ev.py", src)
        rep = _run(p)
        assert "E006" in _codes(rep.errors)

    def test_deny_dunder_import(self, tmp_path):
        src = """
            def control(a, b, c):
                m = __import__("os")
                return 0.0, 0.5
        """
        p = _write(tmp_path, "di.py", src)
        rep = _run(p)
        assert "E006" in _codes(rep.errors)


# ---------------------------------------------------------------------------
# R9 可疑属性
# ---------------------------------------------------------------------------

class TestSuspiciousAttrs:
    def test_subclasses_access_is_error(self, tmp_path):
        """__subclasses__ 是真·逃逸属性 → E007 error。"""
        src = """
            def control(a, b, c):
                x = ().__class__.__subclasses__()
                return 0.0, 0.5
        """
        p = _write(tmp_path, "sus.py", src)
        rep = _run(p)
        assert "E007" in _codes(rep.errors)
        assert not rep.passed

    def test_globals_access_is_error(self, tmp_path):
        """__globals__ 同样是 E007。"""
        src = """
            def control(a, b, c):
                g = control.__globals__
                return 0.0, 0.5
        """
        p = _write(tmp_path, "g.py", src)
        rep = _run(p)
        assert "E007" in _codes(rep.errors)

    def test_loader_spec_is_warn_not_error(self, tmp_path):
        """__loader__/__spec__ 应只 warn，不阻塞通过。"""
        src = """
            def control(a, b, c):
                _ = __loader__     # 顶层隐式存在的名字
                return 0.0, 0.5
        """
        p = _write(tmp_path, "ls.py", src)
        rep = _run(p)
        # __loader__ 作为 Name 引用不再被扫描（只扫 Attribute），故 passed
        assert rep.passed, rep.errors

    def test_loader_attr_access_warns(self, tmp_path):
        """__loader__ 作为属性访问才触发 W007。"""
        src = """
            def control(a, b, c):
                _ = control.__module__   # OK，不在名单
                return 0.0, 0.5
            class X:
                pass
            _ = X().__spec__ if hasattr(X(), '__spec__') else None
        """
        p = _write(tmp_path, "attr.py", src)
        rep = _run(p)
        # __spec__ 作为属性访问 → W007
        assert "W007" in _codes(rep.warnings)


# ---------------------------------------------------------------------------
# R10-R14 接口 / 返回值
# ---------------------------------------------------------------------------

class TestInterface:
    def test_missing_control_fails(self, tmp_path):
        src = """
            def drive(a, b, c):
                return 0.0, 0.5
        """
        p = _write(tmp_path, "nm.py", src)
        rep = _run(p)
        assert "E008" in _codes(rep.errors)

    def test_wrong_arity_warns(self, tmp_path):
        src = """
            def control(a, b):
                return 0.0, 0.5
        """
        p = _write(tmp_path, "ar.py", src)
        rep = _run(p)
        assert "W008" in _codes(rep.warnings)

    def test_return_not_tuple(self, tmp_path):
        src = """
            def control(a, b, c):
                return 0.5
        """
        p = _write(tmp_path, "rt.py", src)
        rep = _run(p)
        assert "E012" in _codes(rep.errors)

    def test_return_out_of_range_warns(self, tmp_path):
        src = """
            def control(a, b, c):
                return 2.0, 5.0
        """
        p = _write(tmp_path, "oor.py", src)
        rep = _run(p)
        assert "W013" in _codes(rep.warnings)
        assert rep.passed  # warn 不阻塞

    def test_control_raises_is_warn(self, tmp_path):
        """control() 抛异常 → W011 warn（线上会 try/except 回落到 (0, 0)）。

        这是对 P0-3 修复的断言：validator 不应比线上更严格，首调异常只 warn。
        """
        src = """
            def control(a, b, c):
                raise RuntimeError("boom")
        """
        p = _write(tmp_path, "raise.py", src)
        rep = _run(p)
        assert "W011" in _codes(rep.warnings)
        # passed=True —— 因为只有 warn
        assert rep.passed, rep.errors


# ---------------------------------------------------------------------------
# 结构化输出 / strict 语义（通过 Python API 验证，CLI 留给冒烟测试）
# ---------------------------------------------------------------------------

class TestReportShape:
    def test_report_to_dict_has_required_fields(self, tmp_path):
        p = _write(tmp_path, "ok.py", GOOD_SRC)
        rep = _run(p)
        d = rep.to_dict()
        assert set(d.keys()) == {"passed", "errors", "warnings", "summary", "meta"}
        assert isinstance(d["passed"], bool)
        assert isinstance(d["errors"], list)
        assert isinstance(d["warnings"], list)

    def test_meta_contains_perf_info(self, tmp_path):
        p = _write(tmp_path, "ok.py", GOOD_SRC)
        rep = _run(p)
        assert "avg_call_ms" in rep.meta
        assert "mock_calls" in rep.meta
        assert rep.meta["mock_calls"] == DEFAULT_RULES["runtime"]["mock_calls"]


if __name__ == "__main__":   # 便于手动 `python tests/test_validator.py`
    sys.exit(pytest.main([__file__, "-v"]))

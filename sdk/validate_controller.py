"""
validate_controller.py — AI Racer 本地代码合规验证工具

职责
----
在学生提交代码到服务器之前，尽可能模拟线上沙箱（`simnode/car_sandbox.py` +
`sandbox_runner.py`）的静态 + 轻量动态检查，避免到服务器才发现不合规。

两种调用方式
------------

1) CLI（学生自查 / CI）:

    python sdk/validate_controller.py --code-path my_controller.py
    python sdk/validate_controller.py --code-path my_controller.py --json
    python sdk/validate_controller.py --code-path my_controller.py --rules sdk/rules.yaml --strict

2) Python API（被 run_local.py 或后端测试 import）:

    from sdk.validate_controller import Validator, ValidationReport
    report: ValidationReport = Validator().check("my_controller.py")
    if not report.passed:
        ...

退出码
------
    0 — 通过（可能含 warning；启用 --strict 时 warning 也算失败）
    1 — 有 error
    2 — 校验器自身异常（参数错误、rules.yaml 解析失败等）
    3 — 仅 warnings 且 --strict 开启

设计原则
--------
* **规则即数据**：黑白名单、大小上限、返回值范围等全部从 rules.yaml 读取，不硬编码
* **AST 优先**：禁用 API 检测走 AST，不用脆弱的正则匹配函数名
* **结构化输出**：errors / warnings / summary 皆为字段化 dict，便于机器消费
* **向后兼容**：仍然支持 `--code-path` + 人类可读文本输出作为默认模式
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib.abc
import importlib.util
import json
import os
import pathlib
import py_compile
import sys
import time
from typing import Any, Iterable, Optional

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover — 环境极端情况
    _HAS_NUMPY = False

try:
    import yaml  # pyyaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

SEVERITY_ERROR = "error"
SEVERITY_WARN = "warn"


@dataclasses.dataclass
class Finding:
    """单条检查发现（通过不产生 Finding；Finding 必有 severity）。"""
    code: str           # 规则编号，例如 "E004"
    severity: str       # "error" | "warn"
    message: str
    lineno: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.lineno is not None:
            d["lineno"] = self.lineno
        return d


@dataclasses.dataclass
class ValidationReport:
    passed: bool
    errors:   list[Finding] = dataclasses.field(default_factory=list)
    warnings: list[Finding] = dataclasses.field(default_factory=list)
    summary:  str = ""
    meta:     dict[str, Any] = dataclasses.field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        if finding.severity == SEVERITY_ERROR:
            self.errors.append(finding)
        else:
            self.warnings.append(finding)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed":   self.passed,
            "errors":   [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.warnings],
            "summary":  self.summary,
            "meta":     self.meta,
        }


# ---------------------------------------------------------------------------
# 默认规则（当 rules.yaml 缺失或缺字段时使用；与 sdk/rules.yaml 保持同步）
# ---------------------------------------------------------------------------

DEFAULT_RULES: dict[str, Any] = {
    "file": {"max_size_kb": 100, "encoding": "utf-8"},
    "imports": {
        "allow": [
            "numpy", "cv2", "math", "collections",
            "heapq", "functools", "itertools", "typing",
            "__future__",
        ],
        "deny": [
            "os", "sys", "socket", "subprocess", "multiprocessing",
            "threading", "time", "datetime", "io", "builtins",
            "ctypes", "pathlib", "shutil", "tempfile",
            "requests", "urllib", "http", "ftplib", "smtplib",
            "signal", "gc", "inspect", "importlib",
            "glob", "fnmatch", "winreg", "nt",
        ],
        "warn_on_unknown": True,
    },
    "builtins": {
        "deny_calls": [
            "eval", "exec", "compile", "open", "globals", "locals",
            "input", "breakpoint", "__import__", "vars",
        ],
        "suspicious_attrs": [
            "__globals__", "__builtins__", "__subclasses__",
            "__code__", "__closure__", "__mro__", "func_globals",
            "__loader__", "__spec__",
        ],
    },
    "interface": {
        "entry": "control",
        "arity": 3,
        "return_ranges": {"steering": [-1.0, 1.0], "speed": [0.0, 1.0]},
    },
    "runtime": {
        "soft_timeout_ms": 20,
        "mock_calls": 10,
        "image_shape": [480, 640, 3],
        "image_dtype": "uint8",
    },
}


def _load_rules(path: Optional[pathlib.Path]) -> dict[str, Any]:
    """加载 rules.yaml，缺失字段用 DEFAULT_RULES 兜底。

    若未安装 pyyaml 则 warn 一条并直接使用 DEFAULT_RULES，
    保证学生环境即便没装 yaml 也能完成基础校验。
    """
    if path is None:
        return DEFAULT_RULES

    if not path.is_file():
        raise FileNotFoundError(f"rules 文件不存在: {path}")
    if not _HAS_YAML:
        print(
            "[validator][warn] 未安装 pyyaml，改用内置默认规则。"
            "若需自定义请 `pip install pyyaml`。",
            file=sys.stderr,
        )
        return DEFAULT_RULES

    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged: dict[str, Any] = {
        k: (dict(v) if isinstance(v, dict) else v)
        for k, v in DEFAULT_RULES.items()
    }
    for k, v in loaded.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class Validator:
    """集中所有检查。每个 `_check_*` 方法把 Finding 写入 report，不抛异常。"""

    def __init__(self, rules: Optional[dict[str, Any]] = None):
        self.rules = rules if rules is not None else DEFAULT_RULES

    # ---- 公共入口 ----

    def check(self, code_path: "os.PathLike[str] | str") -> ValidationReport:
        report = ValidationReport(passed=True)
        path = pathlib.Path(code_path)
        if not path.is_file():
            report.add(Finding("E000", SEVERITY_ERROR, f"文件不存在: {path}"))
            report.passed = False
            report.summary = "校验中止：文件不存在"
            return report

        # Step 1：文件基础检查
        self._check_file_size(path, report)
        source = self._check_encoding(path, report)
        if source is None:
            report.passed = False
            report.summary = f"校验失败：文件编码错误（{len(report.errors)} error）"
            return report

        # Step 2：语法
        if not self._check_syntax(path, report):
            report.passed = False
            report.summary = f"校验失败：语法错误（{len(report.errors)} error）"
            return report

        # Step 3：AST 静态检查
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as e:
            report.add(Finding("E003", SEVERITY_ERROR,
                               f"AST 解析失败: {e.msg}", lineno=e.lineno))
            report.passed = False
            report.summary = "校验失败：AST 解析错误"
            return report

        self._check_imports_ast(tree, report)
        self._check_builtin_calls_ast(tree, report)
        self._check_suspicious_attrs_ast(tree, report)
        self._check_entry_defined_ast(tree, report)

        # Step 4：动态加载 + mock 调用
        #        只在前面没有致命 error 时尝试，避免被语法问题之外的错误淹没
        blocking_codes = {"E004", "E005", "E010"}
        has_blocking = any(f.code in blocking_codes for f in report.errors)
        if not has_blocking:
            module = self._load_module(path, report)
            if module is not None:
                self._check_entry_callable(module, report)
                self._check_mock_call(module, report)

        # 汇总
        report.passed = len(report.errors) == 0
        report.summary = self._render_summary(report)
        return report

    # ---- 各检查实现 ----

    def _check_file_size(self, path: pathlib.Path, report: ValidationReport) -> None:
        limit_kb = int(self.rules.get("file", {}).get("max_size_kb", 100))
        size_kb = path.stat().st_size / 1024
        if size_kb > limit_kb:
            report.add(Finding(
                "E001", SEVERITY_ERROR,
                f"文件过大：{size_kb:.1f}KB > 上限 {limit_kb}KB",
            ))

    def _check_encoding(self, path: pathlib.Path,
                        report: ValidationReport) -> Optional[str]:
        encoding = self.rules.get("file", {}).get("encoding", "utf-8")
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as e:
            report.add(Finding(
                "E002", SEVERITY_ERROR,
                f"文件不是合法 {encoding} 编码：{e}",
            ))
            return None

    def _check_syntax(self, path: pathlib.Path, report: ValidationReport) -> bool:
        try:
            py_compile.compile(str(path), doraise=True)
            return True
        except py_compile.PyCompileError as e:
            lineno: Optional[int] = None
            exc = getattr(e, "exc_value", None)
            if isinstance(exc, SyntaxError):
                lineno = exc.lineno
            report.add(Finding("E003", SEVERITY_ERROR,
                               f"语法错误：{e}", lineno=lineno))
            return False

    def _check_imports_ast(self, tree: ast.AST, report: ValidationReport) -> None:
        cfg = self.rules.get("imports", {})
        deny = set(cfg.get("deny", []))
        allow = set(cfg.get("allow", []))
        warn_unknown = bool(cfg.get("warn_on_unknown", True))

        def _base(name: Optional[str]) -> str:
            return (name or "").split(".")[0]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = _base(alias.name)
                    self._classify_import(base, alias.name, node.lineno,
                                          deny, allow, warn_unknown, report)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    report.add(Finding(
                        "E005", SEVERITY_ERROR,
                        f"禁止相对 import（level={node.level}）",
                        lineno=node.lineno,
                    ))
                    continue
                base = _base(node.module)
                if base:
                    self._classify_import(base, node.module or base, node.lineno,
                                          deny, allow, warn_unknown, report)

    def _classify_import(
        self, base: str, full: str, lineno: int,
        deny: set, allow: set, warn_unknown: bool,
        report: ValidationReport,
    ) -> None:
        if base in deny:
            report.add(Finding(
                "E004", SEVERITY_ERROR,
                f"禁止导入 '{full}'（属于沙箱黑名单）",
                lineno=lineno,
            ))
        elif base not in allow and warn_unknown:
            report.add(Finding(
                "W004", SEVERITY_WARN,
                f"'{full}' 不在沙箱白名单，线上可能无法加载。"
                f"白名单：{', '.join(sorted(allow))}",
                lineno=lineno,
            ))

    def _check_builtin_calls_ast(self, tree: ast.AST,
                                 report: ValidationReport) -> None:
        deny = set(self.rules.get("builtins", {}).get("deny_calls", []))
        if not deny:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in deny:
                    report.add(Finding(
                        "E006", SEVERITY_ERROR,
                        f"禁止调用内置 '{node.func.id}()'",
                        lineno=node.lineno,
                    ))

    def _check_suspicious_attrs_ast(self, tree: ast.AST,
                                    report: ValidationReport) -> None:
        attrs = set(self.rules.get("builtins", {}).get("suspicious_attrs", []))
        if not attrs:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in attrs:
                report.add(Finding(
                    "W007", SEVERITY_WARN,
                    f"访问了可疑属性 '{node.attr}'（常用于沙箱逃逸）",
                    lineno=node.lineno,
                ))
            elif isinstance(node, ast.Name) and node.id in attrs:
                report.add(Finding(
                    "W007", SEVERITY_WARN,
                    f"引用了可疑名字 '{node.id}'",
                    lineno=node.lineno,
                ))

    def _check_entry_defined_ast(self, tree: ast.AST,
                                 report: ValidationReport) -> None:
        entry = self.rules.get("interface", {}).get("entry", "control")
        expected_arity = int(self.rules.get("interface", {}).get("arity", 3))

        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == entry:
                n_args = (len(node.args.args)
                          + len(node.args.posonlyargs)
                          + len(node.args.kwonlyargs))
                has_vararg = node.args.vararg is not None
                if not has_vararg and n_args != expected_arity:
                    report.add(Finding(
                        "W008", SEVERITY_WARN,
                        f"{entry} 形参数量为 {n_args}，期望 {expected_arity}"
                        f"（left_img, right_img, timestamp）",
                        lineno=node.lineno,
                    ))
                return
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == entry:
                        return  # callable 赋值，放行，交给动态检查

    def _load_module(self, path: pathlib.Path,
                     report: ValidationReport) -> Optional[Any]:
        """用受限 meta_path 加载，模拟线上沙箱的 ImportError 行为。"""
        deny = set(self.rules.get("imports", {}).get("deny", []))

        class _SandboxHook(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                base = fullname.split(".")[0]
                if base in deny:
                    raise ImportError(
                        f"[sandbox-sim] 禁止导入 '{fullname}'（黑名单）"
                    )
                return None

        hook = _SandboxHook()
        sys.meta_path.insert(0, hook)
        saved_name = "_airacer_validator_target"
        try:
            spec = importlib.util.spec_from_file_location(saved_name, path)
            if spec is None or spec.loader is None:
                report.add(Finding("E011", SEVERITY_ERROR, "无法构造模块 spec"))
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except ImportError as e:
            report.add(Finding("E010", SEVERITY_ERROR,
                               f"加载时触发禁止 import：{e}"))
            return None
        except Exception as e:
            report.add(Finding("E011", SEVERITY_ERROR,
                               f"模块加载失败：{type(e).__name__}: {e}"))
            return None
        finally:
            try:
                sys.meta_path.remove(hook)
            except ValueError:
                pass
            sys.modules.pop(saved_name, None)

    def _check_entry_callable(self, module: Any,
                              report: ValidationReport) -> None:
        entry = self.rules.get("interface", {}).get("entry", "control")
        fn = getattr(module, entry, None)
        if not callable(fn):
            report.add(Finding(
                "E008", SEVERITY_ERROR,
                f"模块未定义可调用的 '{entry}' 函数",
            ))

    def _check_mock_call(self, module: Any,
                         report: ValidationReport) -> None:
        entry = self.rules.get("interface", {}).get("entry", "control")
        fn = getattr(module, entry, None)
        if not callable(fn):
            return  # 已由 _check_entry_callable 记录

        shape = tuple(self.rules.get("runtime", {})
                                 .get("image_shape", [480, 640, 3]))
        n_calls = int(self.rules.get("runtime", {}).get("mock_calls", 10))
        soft_ms = int(self.rules.get("runtime", {}).get("soft_timeout_ms", 20))
        ranges = self.rules.get("interface", {}).get("return_ranges", {})

        if _HAS_NUMPY:
            left  = np.zeros(shape, dtype=np.uint8)
            right = np.zeros(shape, dtype=np.uint8)
        else:
            report.add(Finding(
                "W012", SEVERITY_WARN,
                "未安装 numpy，mock 调用使用占位对象，可能触发假阳性",
            ))
            class _Fake:
                pass
            left = _Fake()
            left.shape = tuple(shape)    # type: ignore[attr-defined]
            left.dtype = "uint8"         # type: ignore[attr-defined]
            right = left

        # 首调：做接口/返回值检查
        try:
            result = fn(left, right, 0.0)
        except Exception as e:
            report.add(Finding(
                "E011", SEVERITY_ERROR,
                f"{entry}() 首次调用抛异常：{type(e).__name__}: {e}",
            ))
            return

        if not (isinstance(result, (tuple, list)) and len(result) == 2):
            report.add(Finding(
                "E012", SEVERITY_ERROR,
                f"{entry}() 必须返回长度为 2 的 tuple/list，实际：{type(result).__name__}",
            ))
            return
        try:
            steering = float(result[0])
            speed = float(result[1])
        except (TypeError, ValueError) as e:
            report.add(Finding(
                "E012", SEVERITY_ERROR,
                f"{entry}() 返回值不可转为 float：{e}",
            ))
            return

        s_lo, s_hi = ranges.get("steering", [-1.0, 1.0])
        v_lo, v_hi = ranges.get("speed",    [0.0, 1.0])
        if not (s_lo <= steering <= s_hi):
            report.add(Finding(
                "W013", SEVERITY_WARN,
                f"steering 超出 [{s_lo}, {s_hi}]：{steering}（线上会被 clamp）",
            ))
        if not (v_lo <= speed <= v_hi):
            report.add(Finding(
                "W013", SEVERITY_WARN,
                f"speed 超出 [{v_lo}, {v_hi}]：{speed}（线上会被 clamp）",
            ))

        # 耗时粗测
        t0 = time.perf_counter_ns()
        for i in range(n_calls):
            try:
                fn(left, right, float(i) * 0.032)
            except Exception as e:
                report.add(Finding(
                    "E011", SEVERITY_ERROR,
                    f"{entry}() 第 {i+2} 次调用抛异常：{type(e).__name__}: {e}",
                ))
                return
        elapsed_ns = time.perf_counter_ns() - t0
        avg_ms = elapsed_ns / n_calls / 1e6
        report.meta["mock_calls"] = n_calls
        report.meta["avg_call_ms"] = round(avg_ms, 3)
        report.meta["soft_timeout_ms"] = soft_ms

        if avg_ms > soft_ms:
            report.add(Finding(
                "W014", SEVERITY_WARN,
                f"{entry}() 平均耗时 {avg_ms:.2f}ms，超过软上限 {soft_ms}ms，"
                f"线上会频繁触发超时惩罚",
            ))
        elif avg_ms > soft_ms * 0.7:
            report.add(Finding(
                "W014", SEVERITY_WARN,
                f"{entry}() 平均耗时 {avg_ms:.2f}ms，接近软上限 {soft_ms}ms",
            ))

    @staticmethod
    def _render_summary(report: ValidationReport) -> str:
        n_e, n_w = len(report.errors), len(report.warnings)
        if n_e == 0 and n_w == 0:
            return "全部通过。"
        if n_e == 0:
            return f"通过（含 {n_w} 条 warning）。"
        return f"未通过：{n_e} error, {n_w} warning。"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _supports_unicode_glyphs() -> bool:
    """检测当前 stdout 是否能编码 ✓/✗。PowerShell 默认 cp936 (GBK) 编码不支持。"""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "✓✗".encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _render_text(report: ValidationReport, code_path: str) -> str:
    lines = [f"正在验证: {code_path}"]
    core_groups = [
        ("语法检查",     {"E003"}),
        ("文件检查",     {"E001", "E002"}),
        ("禁止导入扫描", {"E004", "E005", "E010"}),
        ("禁用内置扫描", {"E006"}),
        ("接口验证",     {"E008", "E011", "E012"}),
    ]
    err_codes = {f.code for f in report.errors}
    ok_mark, bad_mark = ("✓", "✗") if _supports_unicode_glyphs() else ("[OK]", "[FAIL]")
    for name, codes in core_groups:
        mark = bad_mark if err_codes & codes else ok_mark
        lines.append(f"  {mark} {name}")

    if report.errors:
        lines.append("")
        lines.append("错误：")
        for f in report.errors:
            loc = f" (line {f.lineno})" if f.lineno else ""
            lines.append(f"  - [{f.code}]{loc} {f.message}")
    if report.warnings:
        lines.append("")
        lines.append("警告：")
        for f in report.warnings:
            loc = f" (line {f.lineno})" if f.lineno else ""
            lines.append(f"  - [{f.code}]{loc} {f.message}")
    if report.meta:
        lines.append("")
        lines.append("性能：")
        for k, v in report.meta.items():
            lines.append(f"  {k} = {v}")
    lines.append("")
    lines.append(report.summary)
    return "\n".join(lines)


def _main(argv: Optional[Iterable[str]] = None) -> int:
    # Windows PowerShell 默认 cp936，中文+emoji 都会崩；尽量切 UTF-8。
    # 失败也没关系：_supports_unicode_glyphs 会自动降级到 ASCII 标记。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="AI Racer 控制器本地验证工具",
    )
    parser.add_argument("--code-path", required=True,
                        help="team_controller.py 文件路径")
    parser.add_argument("--rules", default=None,
                        help="rules.yaml 规则文件路径（缺省使用 sdk/rules.yaml）")
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 格式输出结果")
    parser.add_argument("--strict", action="store_true",
                        help="warning 也视为未通过（退出码 3）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    rules_path: Optional[pathlib.Path] = None
    if args.rules:
        rules_path = pathlib.Path(args.rules).expanduser().resolve()
    else:
        default_rules = pathlib.Path(__file__).resolve().parent / "rules.yaml"
        if default_rules.is_file():
            rules_path = default_rules

    try:
        rules = _load_rules(rules_path)
    except Exception as e:
        msg = f"[validator] 加载 rules 失败：{e}"
        if args.json:
            print(json.dumps({"passed": False, "errors": [msg],
                              "warnings": [], "summary": msg}, ensure_ascii=False))
        else:
            print(msg, file=sys.stderr)
        return 2

    validator = Validator(rules)
    report = validator.check(args.code_path)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_text(report, args.code_path))

    if not report.passed:
        return 1
    if args.strict and report.warnings:
        return 3
    return 0


# 供外部 import 的便利函数
def validate(code_path: str,
             rules_path: Optional[str] = None) -> ValidationReport:
    """Python API 入口。"""
    rp = pathlib.Path(rules_path).expanduser().resolve() if rules_path else None
    if rp is None:
        default_rules = pathlib.Path(__file__).resolve().parent / "rules.yaml"
        if default_rules.is_file():
            rp = default_rules
    rules = _load_rules(rp)
    return Validator(rules).check(code_path)


if __name__ == "__main__":
    sys.exit(_main())

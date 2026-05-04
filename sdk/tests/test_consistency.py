"""
sdk/tests/test_consistency.py
─────────────────────────────
确保以下三处黑白名单保持一致（对应验收标准 #5「本地=服务器行为一致」）：

  1. sdk/rules.yaml                                       （校验规则源）
  2. simnode/car_sandbox.py                               （race_runner 用的沙箱）
  3. simnode/webots/controllers/car/sandbox_runner.py    （Webots 子进程用的沙箱）

一旦三处漂移，validator 就可能误报/漏报，学生本地过线上拒。此测试做硬失败。

运行：
    cd pkudsa.airacer
    pytest sdk/tests/test_consistency.py -v
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SDK_DIR = REPO_ROOT / "sdk"
SANDBOX_RUNNER = (
    REPO_ROOT / "simnode" / "webots" / "controllers" / "car" / "sandbox_runner.py"
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))


def _load_rules_yaml() -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("pyyaml not installed; skipping YAML-driven consistency")
    return yaml.safe_load((SDK_DIR / "rules.yaml").read_text(encoding="utf-8"))


def _parse_blocked_prefixes_literal(path: pathlib.Path) -> set[str]:
    """Extract the ``BLOCKED_PREFIXES = frozenset([...])`` literal from a module.

    Supports both ``ast.Assign`` (``X = frozenset([...])``) and ``ast.AnnAssign``
    (``X: frozenset = frozenset([...])``).
    """
    import ast

    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        target_name = None
        value = None
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "BLOCKED_PREFIXES":
                    target_name = tgt.id
                    value = node.value
                    break
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if isinstance(tgt, ast.Name) and tgt.id == "BLOCKED_PREFIXES":
                target_name = tgt.id
                value = node.value
        if target_name is None or value is None:
            continue
        # Expect frozenset([...]) or {...}
        inner = None
        if isinstance(value, ast.Call) and value.args:
            inner = value.args[0]
        elif isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            inner = value
        if inner is None or not hasattr(inner, "elts"):
            continue
        return {
            elt.value for elt in inner.elts   # type: ignore[attr-defined]
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        }
    raise AssertionError(f"Could not locate BLOCKED_PREFIXES in {path}")


# ---------------------------------------------------------------------------
# 1. rules.yaml 的 deny 集合必须是 car_sandbox.py::_BLOCKED_PREFIXES 的超集
#    （rules.yaml 可以更严格，但不能更宽松）
# ---------------------------------------------------------------------------

def test_rules_yaml_deny_is_superset_of_car_sandbox():
    from simnode.car_sandbox import _BLOCKED_PREFIXES
    rules = _load_rules_yaml()
    yaml_deny = set(rules["imports"]["deny"])
    car_deny = set(_BLOCKED_PREFIXES)
    missing = car_deny - yaml_deny
    assert not missing, (
        f"simnode/car_sandbox.py::_BLOCKED_PREFIXES 有，但 sdk/rules.yaml 的 "
        f"deny 里缺：{sorted(missing)}。学生代码在 validator 看来合规但线上会"
        f"被 ImportError 拒绝。"
    )


def test_rules_yaml_deny_is_superset_of_sandbox_runner():
    """sandbox_runner.py 是 Webots 子进程的拦截器，也不能漏。"""
    blocked = _parse_blocked_prefixes_literal(SANDBOX_RUNNER)
    rules = _load_rules_yaml()
    yaml_deny = set(rules["imports"]["deny"])
    missing = blocked - yaml_deny
    assert not missing, (
        f"sandbox_runner.py::BLOCKED_PREFIXES 有，但 sdk/rules.yaml 的 deny 里"
        f"缺：{sorted(missing)}。"
    )


# ---------------------------------------------------------------------------
# 2. rules.yaml 的 allow 必须是 car_sandbox.py::_ALLOWED_MODULES 的子集
#    （validator 不能比线上更宽松）
# ---------------------------------------------------------------------------

def test_rules_yaml_allow_is_subset_of_car_sandbox():
    from simnode.car_sandbox import _ALLOWED_MODULES
    rules = _load_rules_yaml()
    yaml_allow = set(rules["imports"]["allow"])
    car_allow = set(_ALLOWED_MODULES.keys())
    extra = yaml_allow - car_allow
    assert not extra, (
        f"sdk/rules.yaml 的 allow 里有但 car_sandbox.py::_ALLOWED_MODULES 里没有："
        f"{sorted(extra)}。validator 会放行线上会拒的模块（漏报）。"
    )


# ---------------------------------------------------------------------------
# 3. car_sandbox.py 与 sandbox_runner.py 的 black/white list 应互相对齐
# ---------------------------------------------------------------------------

def test_car_sandbox_and_sandbox_runner_blacklists_consistent():
    from simnode.car_sandbox import _BLOCKED_PREFIXES
    blocked = _parse_blocked_prefixes_literal(SANDBOX_RUNNER)
    # 两处应完全相等
    sym_diff = set(_BLOCKED_PREFIXES) ^ blocked
    assert not sym_diff, (
        "car_sandbox.py::_BLOCKED_PREFIXES 与 sandbox_runner.py::BLOCKED_PREFIXES "
        f"不一致，差异：{sorted(sym_diff)}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

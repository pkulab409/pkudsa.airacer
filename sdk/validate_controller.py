"""
validate_controller.py — 本地合规验证工具，对应 Avalon 代码合规检查

用法：
    python validate_controller.py --code-path my_controller.py

验证内容（与 Backend 提交检查逻辑完全一致）：
  1. Python 语法合法（py_compile）
  2. control 函数存在且可调用
  3. 静态 AST 扫描：禁止 import 列表
  4. Mock 调用：检查返回值类型和数值范围
"""

import argparse
import ast
import importlib.util
import pathlib
import py_compile
import sys
import tempfile

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# 禁止导入的模块（与 car_sandbox.py 白名单对应的黑名单）
# ---------------------------------------------------------------------------

BLOCKED_IMPORTS = frozenset([
    "os", "sys", "socket", "subprocess", "multiprocessing",
    "threading", "time", "datetime", "io", "builtins",
    "ctypes", "pathlib", "shutil", "tempfile",
    "requests", "urllib", "http", "ftplib", "smtplib",
    "signal", "gc", "inspect", "importlib",
])


def _check_syntax(code_path: str) -> None:
    """Step 1: py_compile 语法检查。"""
    try:
        py_compile.compile(code_path, doraise=True)
    except py_compile.PyCompileError as e:
        raise ValueError(f"语法错误: {e}")


def _check_banned_imports(code_path: str) -> None:
    """Step 2: AST 静态扫描禁止 import。"""
    with open(code_path, "r", encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return  # 语法错误已在 Step 1 报告

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module] if node.module else []
            for name in names:
                base = name.split(".")[0] if name else ""
                if base in BLOCKED_IMPORTS:
                    raise ValueError(
                        f"禁止导入模块: '{name}'（第 {node.lineno} 行）\n"
                        f"允许使用：numpy, cv2, math, collections, heapq, functools, itertools"
                    )


def _check_interface(code_path: str) -> None:
    """Step 3: 载入模块，检查 control() 函数签名与返回值。"""
    spec   = importlib.util.spec_from_file_location("_check_ctrl", code_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as e:
        raise ValueError(f"导入禁止模块: {e}")
    except Exception as e:
        raise ValueError(f"模块加载失败: {e}")

    if not callable(getattr(module, "control", None)):
        raise ValueError("模块中未定义可调用的 'control' 函数")

    if _HAS_NUMPY:
        dummy_l = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy_r = np.zeros((480, 640, 3), dtype=np.uint8)
    else:
        # numpy 不可用时用模拟对象
        class _FakeArray:
            shape = (480, 640, 3)
            dtype = "uint8"
        dummy_l = dummy_r = _FakeArray()

    try:
        result = module.control(dummy_l, dummy_r, 0.0)
    except Exception as e:
        raise ValueError(f"control() 调用时抛出异常: {e}")

    if not (isinstance(result, (tuple, list)) and len(result) == 2):
        raise ValueError(
            f"control() 必须返回长度为 2 的 tuple/list，实际返回: {type(result).__name__}"
        )

    steering, speed = float(result[0]), float(result[1])
    if not (-1.0 <= steering <= 1.0):
        raise ValueError(f"steering 超出范围 [-1.0, 1.0]：{steering}")
    if not (0.0 <= speed <= 1.0):
        raise ValueError(f"speed 超出范围 [0.0, 1.0]：{speed}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def validate(code_path: str) -> None:
    p = pathlib.Path(code_path)
    if not p.exists():
        print(f"[错误] 文件不存在: {code_path}")
        sys.exit(1)

    print(f"正在验证: {code_path}")

    checks = [
        ("语法检查",         _check_syntax),
        ("禁止导入扫描",      _check_banned_imports),
        ("接口验证",         _check_interface),
    ]

    all_ok = True
    for name, fn in checks:
        try:
            fn(str(p))
            print(f"  ✓ {name}")
        except ValueError as e:
            print(f"  ✗ {name}: {e}")
            all_ok = False

    if all_ok:
        print("\n验证通过！代码可以提交。")
    else:
        print("\n验证失败，请修正上述问题后重新提交。")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Racer 控制器本地验证工具")
    parser.add_argument("--code-path", required=True, help="team_controller.py 文件路径")
    args = parser.parse_args()
    validate(args.code_path)

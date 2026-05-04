import sys
import importlib.abc
import importlib.util


# ---------------------------------------------------------------------------
# 受限导入器
# ---------------------------------------------------------------------------

#
# NOTE: 此处黑白名单必须与下列文件保持一致（唯一事实源见 sdk/rules.yaml）：
#   - simnode/webots/controllers/car/sandbox_runner.py
#   - sdk/rules.yaml
# 若需修改请同步三处；sdk/tests/test_validator.py 会做一致性断言。
#
_ALLOWED_MODULES = {
    "numpy":       "numpy",
    "np":          "numpy",
    "cv2":         "cv2",
    "math":        "math",
    "collections": "collections",
    "heapq":       "heapq",
    "functools":   "functools",
    "itertools":   "itertools",
    "typing":      "typing",        # 纯注解，允许
    "__future__":  "__future__",    # 语法 future 声明
}

_BLOCKED_PREFIXES = (
    "os", "sys", "socket", "subprocess", "multiprocessing",
    "threading", "time", "datetime", "io", "builtins",
    "ctypes", "pathlib", "shutil", "tempfile",
    "requests", "urllib", "http", "ftplib", "smtplib",
    "signal", "gc", "inspect", "importlib",
    # Windows 特定 / 文件系统遍历
    "glob", "fnmatch", "winreg", "nt", "_winapi",
)

_ALLOWED_MSG = (
    "允许使用：numpy, cv2, math, collections, heapq, "
    "functools, itertools, typing, __future__"
)


def _restricted_importer(name, globals=None, locals=None, fromlist=(), level=0):
    actual = _ALLOWED_MODULES.get(name)
    if actual:
        return __import__(actual, globals, locals, fromlist, level)

    for prefix in _BLOCKED_PREFIXES:
        if name == prefix or name.startswith(prefix + "."):
            raise ImportError(f"禁止导入受限模块: {name}。{_ALLOWED_MSG}")

    raise ImportError(f"模块不在白名单中: {name}。{_ALLOWED_MSG}")


# ---------------------------------------------------------------------------
# 受限内置函数字典
# ---------------------------------------------------------------------------

RESTRICTED_BUILTINS = {
    # 类型与转换
    "int":        int,   "float":     float,  "str":       str,
    "bool":       bool,  "list":      list,   "dict":      dict,
    "tuple":      tuple, "set":       set,    "frozenset": frozenset,
    "bytes":      bytes, "bytearray": bytearray, "complex": complex,
    # 数学
    "abs": abs, "round": round, "pow": pow, "divmod": divmod,
    "sum": sum, "min":   min,   "max": max,
    # 迭代
    "len":      len,      "range":    range,    "enumerate": enumerate,
    "zip":      zip,      "map":      map,      "filter":    filter,
    "sorted":   sorted,   "reversed": reversed, "iter":      iter,
    "next":     next,     "slice":    slice,
    # 逻辑
    "all": all, "any": any,
    # 表示
    "chr": chr, "ord": ord, "hex": hex, "oct": oct, "bin": bin,
    "format": format, "ascii": ascii, "repr": repr,
    # 类型检查
    "isinstance":  isinstance,  "issubclass": issubclass, "type":     type,
    "callable":    callable,    "id":         id,         "hash":     hash,
    # 属性
    "getattr": getattr, "hasattr": hasattr, "setattr": setattr,
    "delattr": delattr, "vars":    vars,    "dir":     dir,
    # 类定义
    "__build_class__": __build_class__,
    "object":      object,      "property":    property,
    "staticmethod": staticmethod, "classmethod": classmethod,
    "super":       super,        "memoryview":  memoryview,
    # 常量
    "True": True, "False": False, "None": None,
    "__doc__": None, "__name__": "team_controller",
    # 入口：替换 __import__
    "__import__": _restricted_importer,
    # 异常类（学生代码可能 raise/catch）
    "Exception":           Exception,       "ValueError":       ValueError,
    "TypeError":           TypeError,       "IndexError":       IndexError,
    "KeyError":            KeyError,        "AttributeError":   AttributeError,
    "StopIteration":       StopIteration,   "NameError":        NameError,
    "SyntaxError":         SyntaxError,     "RuntimeError":     RuntimeError,
    "ZeroDivisionError":   ZeroDivisionError, "AssertionError": AssertionError,
    "ImportError":         ImportError,     "NotImplementedError": NotImplementedError,
    "OverflowError":       OverflowError,
    # 故意不暴露：open, eval, exec, globals, locals, compile
}


# ---------------------------------------------------------------------------
# sys.meta_path 拦截器
# ---------------------------------------------------------------------------

class SandboxImportHook(importlib.abc.MetaPathFinder):
    """安装到 sys.meta_path[0] 以拦截白名单外的 import。"""

    _ALLOWED_BASES = frozenset(_ALLOWED_MODULES.keys())

    def find_spec(self, fullname, path, target=None):
        base = fullname.split(".")[0]
        if base not in self._ALLOWED_BASES:
            raise ImportError(f"[Sandbox] '{fullname}' 不在白名单中。{_ALLOWED_MSG}")
        return None


# ---------------------------------------------------------------------------
# Linux 资源限制（Windows 上静默忽略）
# ---------------------------------------------------------------------------

def apply_resource_limits(
    memory_bytes: int = 512 * 1024 * 1024,
    cpu_seconds:  int = 30,
) -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,  (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds,  cpu_seconds))
    except ImportError:
        pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"设置资源限制失败: {e}")

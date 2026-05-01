# AI Racer Bug 报告

> 日期: 2026-05-01
> 范围: 根据 `TEST_MAINTENANCE_CHECKLIST.md` 完善测试后，对源码与测试套件进行验证

## 概览

测试目录相关的可靠性问题已修复并从本报告中移除。以下保留的是源码侧曾经复现的问题，以及当前工作区中的修复和回归验证状态。

## 源码问题

### BUG-001: 提交的 Python 代码在静态安全检查前就可能被执行

- 严重级别: 高
- 所属模块: 后端代码提交校验
- 文件: `server/blueprints/submission.py`
- 现象: 学生提交的代码中如果包含危险导入或危险调用，系统没有先通过 AST 静态检查拒绝，而是进入了导入执行路径。
- 影响: 类似 `import os`、`import subprocess`、`__import__("sys")`、`open(...)`、`eval(...)`、`exec(...)` 的代码可能进入导入/校验流程。根据运行环境不同，这会削弱沙箱假设，并可能带来文件系统、进程或运行时访问风险。
- 根因: `_validate_code()` 原本只对临时文件做编译检查，并通过 `spec.loader.exec_module(module)` 导入执行模块；在执行模块顶层代码前，没有 AST 检查来拒绝禁用导入和危险调用。
- 当前状态: 已在当前工作区修复。
- 修复方式: 在写入/导入临时模块前增加 AST 解析与校验，拦截禁用模块根名、危险内建调用，以及 `__builtins__` 访问。
- 回归测试:
  - `tests/backend/unit/test_submission.py::test_validate_code_forbidden_imports`
  - `tests/security/test_code_sandbox_escape.py`

### BUG-002: 无效密码哈希会导致提交接口崩溃

- 严重级别: 中
- 所属模块: 后端认证
- 文件: `server/blueprints/submission.py`
- 现象: 如果 `teams` 表中的 `password_hash` 不是合法 bcrypt 哈希，`_verify_password()` 会抛出 `ValueError: Invalid salt`。
- 影响: 数据库中的异常数据会把一次正常的认证失败变成 500 服务端错误。
- 根因: 没有处理 `_bcrypt.checkpw()` 抛出的异常。
- 当前状态: 已在当前工作区修复。
- 修复方式: `_verify_password()` 捕获 `ValueError` 并返回 `False`，保持“认证失败”的正常语义。
- 回归测试:
  - `tests/backend/unit/test_submission.py::test_invalid_password_hash_returns_false`


## 验证结果

完整测试套件通过:

```text
PYTHONPATH=. .venv/bin/pytest tests -q
154 passed in 107.87s
```

## 剩余风险

- 当前 AST 沙箱使用的是静态 denylist，可以拦截已知危险导入和调用。若要获得更强隔离，提交代码仍应在单独的受限进程或容器中运行，并配置资源限制。
- 目前性能测试覆盖的是中等规模并发提交负载，尚未模拟持续的比赛级流量。

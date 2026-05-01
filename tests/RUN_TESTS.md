# AI Racer 测试运行指南

本文档说明开发者如何运行 `tests/` 目录中的测试代码。

## 1. 进入项目根目录

所有命令都应在 `pkudsa.airacer` 项目根目录下执行：

```bash
cd pkudsa.airacer
```


## 2. 准备 Python 环境

推荐使用项目已有的虚拟环境 `.venv`：

```bash
source .venv/bin/activate
```

如果需要重新安装依赖：

```bash
pip install -r requirements.txt
pip install -r tests/test_requirements.txt
```

前端单元测试会调用 Node.js：

```bash
node --version
```

如果要运行 Playwright E2E 测试，需要安装浏览器：

```bash
python -m playwright install chromium
```

## 3. 重要环境变量

运行测试时建议显式设置 `PYTHONPATH=.`，确保测试能从项目根目录导入 `server` 包：

```bash
PYTHONPATH=. .venv/bin/pytest tests -q
```

测试夹具会自动创建临时数据库、提交目录和录像目录，通常不需要手动设置：

- `DB_PATH`
- `SUBMISSIONS_DIR`
- `RECORDINGS_DIR`
- `ADMIN_PASSWORD`

## 4. 运行完整测试套件

运行 `tests/` 下全部测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests -q
```

完整测试包含 Playwright 浏览器 E2E，会自动启动本地 `uvicorn` 测试服务，因此耗时较长。

## 5. 按模块运行测试

后端单元测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/unit -q
```

后端集成测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/integration -q
```

安全测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests/security -q
```

性能测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests/performance -q
```

前端单元测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests/frontend/unit -q
```

前端 E2E 测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests/frontend/e2e -q
```

## 6. 运行单个测试文件或单个用例

运行单个测试文件：

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/unit/test_submission.py -q
```

运行单个测试函数：

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/unit/test_submission.py::test_validate_code_forbidden_imports -q
```

运行某个类中的单个测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests/security/test_code_sandbox_escape.py::TestForbiddenImports::test_import_os_blocked -q
```

## 7. 前端单元测试说明

前端单元测试入口是：

```text
tests/frontend/unit/test_frontend_unit.py
```

该 pytest 文件会调用：

```text
tests/frontend/unit/frontend_unit_tests.mjs
```

因此运行前端单元测试前需要确保本机可执行 `node`。

## 8. 前端 E2E 测试说明

E2E 测试位于：

```text
tests/frontend/e2e/
```

目录级 fixture 定义在：

```text
tests/frontend/e2e/conftest.py
```

运行时会自动：

1. 创建临时 SQLite 数据库。
2. 创建临时 submissions/recordings 目录。
3. 设置 `ADMIN_PASSWORD=12345`。
4. 启动本地 `uvicorn server.app:app`。
5. 预置默认赛区 `zone1`。
6. 使用 Playwright Chromium 访问页面并执行流程测试。

如果系统限制浏览器进程启动，可能需要在非沙箱环境或本机终端中运行 E2E 命令。

## 9. 常见问题

### ModuleNotFoundError: No module named 'server'

说明没有从项目根目录运行，或没有设置 `PYTHONPATH`。

解决：

```bash
PYTHONPATH=. .venv/bin/pytest tests -q
```

### BrowserType.launch 失败

通常是 Playwright 浏览器未安装或当前环境限制浏览器启动。

先安装浏览器：

```bash
python -m playwright install chromium
```

如果仍失败，请在本机终端中运行 E2E 测试。

### node: command not found

说明本机没有 Node.js，无法运行前端单元测试。

解决方式是安装 Node.js，然后重新运行：

```bash
PYTHONPATH=. .venv/bin/pytest tests/frontend/unit -q
```

### 端口 8002 被占用

E2E 测试默认使用 `127.0.0.1:8002`。如果端口被占用，请先停止占用该端口的进程，再重新运行 E2E。

## 10. 推荐开发流程

修改后端逻辑时，优先运行：

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend tests/security -q
```

修改前端 JS 或页面时，优先运行：

```bash
PYTHONPATH=. .venv/bin/pytest tests/frontend/unit tests/frontend/e2e -q
```

提交前建议运行完整测试：

```bash
PYTHONPATH=. .venv/bin/pytest tests -q
```

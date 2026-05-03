# feat(sdk): 本地测试工具链（validator 升级 + 一键启动 + 学生手册）

## 📦 本次 PR 做了什么

> **布局原则**：所有与 SDK 相关的文件都**集中在 `sdk/` 目录下**，便于单独打包分发给学生。本 PR 未修改仓库其它目录（`server/` / `simnode/` / `frontend/`）。

### ✨ 新增（全部在 `sdk/` 下）

| 文件 | 作用 |
|---|---|
| `sdk/rules.yaml` | 校验规则的单一事实源（黑白名单、大小上限、返回值范围、耗时预算）。**仅 SDK 作用域**，不影响 Backend / Sim Node |
| `sdk/run_local.py` | 一键本地运行：校验 → 生成 `race_config.json` → 自动探测并启动 Webots；支持 `--validate-only` / `--skip-validate` / `--fast` / `--minimize` |
| `sdk/examples/team_controller_tutorial.py` | 教学版 PID 循线控制器（~120 行，注释 ≥ 一半），参数集中顶部，学生复制一份即可开始调参 |
| `sdk/tests/test_validator.py` | validator 的 pytest 套件，**20 用例全绿**；覆盖规则正反样本、结构化输出、性能 meta |
| `sdk/docs/local_test_guide.md` | 面向学生的中文手册 v0.1：定位 / 环境 / 5 分钟上手 / 提交前自查 / FAQ / 错误码速查 |
| `sdk/PR_DESCRIPTION.md` | 本 PR 的描述文案留档（审核通过后可由 reviewer 决定是否删除） |

### 🔄 重写 / 升级

- **`sdk/validate_controller.py`** 整体重写：
  - **AST 静态扫描**：import 黑白名单、禁用内置调用、可疑属性访问（逃逸侦测）
  - **动态检查**：在**受限 meta_path hook** 下加载模块，模拟线上沙箱 ImportError 行为
  - **mock 调用**：零图调用 `control()` 10 次，测平均耗时 + 返回值范围
  - **结构化输出**：`ValidationReport` dataclass、`to_dict()`、`--json` CLI
  - **退出码约定**：`0` 通过 / `1` error / `2` 校验器异常 / `3` strict + warn
  - **Python API**：`from sdk.validate_controller import Validator, validate`
  - **pyyaml 可选**：未安装时自动降级到内置默认规则
  - **Windows 终端兼容**：检测到 stdout 不支持 `✓/✗` 时自动降级为 `[OK]/[FAIL]`
  - **向后兼容**：原 `--code-path` 调用方式继续可用，文本输出格式尽量保留

### 📝 同步修订

- `sdk/README_LOCAL.md`：同步 `run_local.py`、`rules.yaml`、`examples/` 到文件清单，补 Option A/B 两种工作流；指向新的 `sdk/docs/local_test_guide.md`
- `sdk/team_controller.py`：修订注释，显式引导学生参考教学版
- `.gitignore`：补充 `.pytest_cache/`

### ➕ 补齐（此前**从未入库**，一并 commit）

上游仓库的 `sdk/` 只跟踪了 `team_controller.py` 与 `validate_controller.py`；本 PR 把三个开发者们本地已有、但从未入库的脚本一并纳入，让 SDK 在新 clone 上即可自洽运行：

- `sdk/check_env.py`
- `sdk/example_controller.py`
- `sdk/make_local_config.py`

### 最终 SDK 目录（本 PR 后）

```
sdk/
├── README_LOCAL.md                 # 英文 quickstart
├── PR_DESCRIPTION.md               # 本 PR 描述（留档）
├── rules.yaml                      # 🆕 校验规则
├── check_env.py                    # ➕ 补齐
├── make_local_config.py            # ➕ 补齐
├── validate_controller.py          # 🔄 重写升级
├── run_local.py                    # 🆕 一键启动
├── team_controller.py              # 官方最小模板
├── example_controller.py           # ➕ 补齐（numpy 循线示例）
├── examples/
│   └── team_controller_tutorial.py # 🆕 PID 教学版
├── docs/
│   └── local_test_guide.md         # 🆕 中文学生手册
└── tests/
    └── test_validator.py           # 🆕 20 个 pytest 用例
```

---

## 🚧 待完善 / 占位事项

| 占位项 | 依赖角色 | 说明 |
|---|---|---|
| `sdk/docs/local_test_guide.md` FAQ Q4 / 反馈渠道 | 课程组 | 官方 issue / 群渠道定了再填 |
| `airacer.wbt` 是否做"学生简化版" | 测试同学 | 当前直接复用 `simnode/webots/worlds/airacer.wbt`；如要专用简化赛道再补 |
| Backend `server/blueprints/submission.py::_validate_code` 的 TODO "与SDK代码审查部分保持一致" | 后端同学 | **本 PR 未触碰后端**（按需求 `rules.yaml` 只管 SDK 作用域）；后续若后端要对齐，可改为 `from sdk.validate_controller import validate` 复用本模块 |
| `simnode/car_sandbox.py` 与 `sandbox_runner.py` 黑名单轻微不一致（Windows 项 `winreg`/`nt` 等） | Sim Node 同学 | 本 PR 的 `rules.yaml` 已做并集，但线上两处仍各自维护，建议后续以 `rules.yaml` 为参考做一次对齐 |

> ⚠️ **所有占位都不影响本 PR 合入**，只是作为后续 issue 的线索。

---

## ✅ 测试说明

### 本地验证步骤（Windows PowerShell）

```powershell
cd pkudsa.airacer

# 1) 依赖
pip install numpy pyyaml pytest

# 2) 跑 validator 单元测试（必须 20/20 通过）
python -m pytest sdk/tests/test_validator.py -v

# 3) 官方模板 + example + 教学版，三份都应通过
python sdk/validate_controller.py --code-path sdk/team_controller.py
python sdk/validate_controller.py --code-path sdk/example_controller.py
python sdk/validate_controller.py --code-path sdk/examples/team_controller_tutorial.py

# 4) JSON / strict 模式冒烟
python sdk/validate_controller.py --code-path sdk/examples/team_controller_tutorial.py --json
python sdk/validate_controller.py --code-path sdk/examples/team_controller_tutorial.py --strict

# 5) 教学版本身可跑 smoke（不依赖 Webots）
python sdk/examples/team_controller_tutorial.py

# 6) 一键启动流程（需本地装 Webots；reviewer 没装可跳过）
python sdk/run_local.py --code-path sdk/examples/team_controller_tutorial.py --validate-only
```

### 预期结果

- `pytest` **20 passed**
- 三份示例控制器都输出 **"全部通过。"**
- 教学版 smoke：`blank`、`left lane`、`right lane` 三行返回值正负号正确
- `--validate-only` 路径不需要 Webots 即可看到 "[run_local] --validate-only 模式，结束。"

---

## 👀 Review 重点

1. **规则设计合理性**：`sdk/rules.yaml` 的黑白名单是否与线上沙箱口径一致？（对比 `simnode/car_sandbox.py::_BLOCKED_PREFIXES` 与 `simnode/webots/controllers/car/sandbox_runner.py::BLOCKED_PREFIXES`）
2. **退出码契约**：`0/1/2/3` 的划分是否清晰、能被 CI 正确消费？
3. **动态加载副作用**：`Validator._load_module` 用 `sys.meta_path.insert(0, hook)` + `try/finally remove`，请检查异常路径是否会泄漏 hook
4. **mock 调用耗时粗测**：10 次是否过少？把 `rules.yaml::runtime.mock_calls` 改大会不会把学生校验弄太慢？
5. **教学版 tutorial**：是否过难/过易？注释密度是否合适？参数常量命名是否自洽？
6. **学生手册覆盖度**：有没有缺漏的"坑点"？FAQ 够不够？
7. **目录布局**：所有 SDK 交付物集中在 `sdk/` 下（含 `docs/`、`tests/`），便于单独打包；如项目统一要求测试放仓库根 `tests/`，请在本 PR 指出，我再做迁移。

---

## 📌 相关文档 / 引用

- 线上代码沙箱：`simnode/car_sandbox.py`
- Webots 侧 controller：`simnode/webots/controllers/car/sandbox_runner.py`
- 后端 submission 校验：`server/blueprints/submission.py`（本 PR 未修改）
- 提交规范：`READMEs/README_code_submission_guide.md`
- 赛事规则：`READMEs/README_race_rules.md`

---

**分支**：`feature/local-test-tool`
**基于**：`local_branch` / `upstream/master`
**提交数**：4 个 commit（`chore` → `feat` → `docs` → `refactor: relocate to sdk/`）
**目标分支**：`master`（请 reviewer 决定 squash / rebase / merge）

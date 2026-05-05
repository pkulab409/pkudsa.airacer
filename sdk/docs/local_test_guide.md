# AI Racer 本地测试手册

> **版本**：v0.3 （草稿）
> **日期**：2026-05-05
> **适用对象**：AI Racer 参赛学生（有 Python 基础，可能从未用过 Webots）
> **状态**：🚧 第三版；`.wbt` 赛道与接口文档 v0.5 定稿后会再次更新

---

## 目录

1. [前言：能做什么，不能做什么](#1-前言)
2. [环境准备](#2-环境准备)
3. [获取 SDK](#3-获取-sdk)
4. [目录速览](#4-目录速览)
5. [5 分钟快速开始](#5-5-分钟快速开始)
6. [编写你的控制器](#6-编写你的控制器)
7. [提交前校验](#7-提交前校验)
8. [常见问题 FAQ](#8-常见问题-faq)
9. [反馈渠道](#9-反馈渠道)

---

## 1. 前言

AI Racer 本地测试工具是一套**在你自己电脑上跑完整 Webots 仿真**的脚手架，让你在提交到服务器之前就能验证控制器是否可用。

### ✅ 本地工具能做什么

- 用 Webots 跑**单车单圈**仿真，可视化观察赛车行为
- 在提交前静态扫描代码，检测语法错误、非法 import、危险内置调用
- mock 调用你的 `control()` 函数，发现返回值错误/耗时超标
- 生成一份 JSON 报告，接入你自己的 CI

### ❌ 本地工具不能做什么

- **不能**模拟多车同场竞技的碰撞惩罚（线上赛制）
- **不能**复现服务器的碰撞判定阈值和积分规则（线上以 `READMEs/README_race_rules.md` 为准）
- **不能**保证本地"能跑"= 线上"跑得好"，线上跑道可能有你没测过的弯道

> 💡 **定位**：本地工具只帮你**排除低级错误**，不替代线上测试队列。

### 与线上环境的关键差异

| 项目 | 本地 | 线上 |
|---|---|---|
| Webots | Windows/Linux 任意版本 | Linux `/usr/bin/webots` |
| Python 环境 | 你自己的 conda/venv | Sim Node 固定 Python 3.10 |
| 世界文件 | `simnode/webots/worlds/{track_basic,track_complex,airacer}.wbt`（`--world` 切换） | 由赛事配置指定 |
| 沙箱隔离 | ❌ 无进程隔离 | ✅ 子进程 + 受限 importer |
| 单帧超时 | 不强制（但 validator 会 warn） | 20 ms 严格超时，3 次作废本圈 |
| 内存/CPU 限制 | 无 | 512MB / 30s CPU（Linux `setrlimit`） |

---

## 2. 环境准备

### 2.1 Python

- **版本**：Python 3.10+（推荐 3.10/3.11；3.13 也验证可用）
- **依赖**：
  ```powershell
  pip install numpy pyyaml
  pip install opencv-python        # 可选：想在控制器里用 cv2 时
  pip install pytest               # 可选：跑 SDK 自带测试时
  ```

### 2.2 Webots

- 下载地址：<https://cyberbotics.com/#download>
- Windows 推荐默认路径：`C:\Program Files\Webots`
- Linux：`sudo apt install webots` 或官网 `.deb`

安装完成后，建议设置环境变量便于 `run_local.py` 自动探测：

```powershell
# Windows
$env:WEBOTS_HOME = "C:\Program Files\Webots"

# Linux/macOS
export WEBOTS_HOME=/usr/local/webots
```

> 💡 如果 `WEBOTS_HOME` 没设，`run_local.py` 也会尝试在 PATH 与常见路径里查找；找不到时会报错并要求用 `--webots` 显式指定。

### 2.3 一键自检

```powershell
python sdk/check_env.py
```

看到 `Environment appears OK for running the local SDK.` 就可以进入下一步。

---

## 3. 获取 SDK

假设你已经从 GitHub 拿到项目仓库：

```bash
git clone <repo-url> pkudsa.airacer
cd pkudsa.airacer
```

你只需要关心 `sdk/` 这一个目录，下文以 `sdk/` 为根展开。

> 💡 以后若只想给学生分发 SDK 部分，可直接打包 `sdk/` + `simnode/webots/` 两个目录，其他文件与学生无关。

---

## 4. 目录速览

```
sdk/
├── README_LOCAL.md                 # 英文 quickstart（精简版）
├── rules.yaml                      # 校验规则（黑白名单、返回值范围等）
├── check_env.py                    # 环境自检脚本
├── worlds.py                       # 🆕 赛道 + 车型目录（--list-worlds 的数据源）
├── make_local_config.py            # 生成 race_config.json 的工具
├── validate_controller.py          # 提交前代码校验器
├── run_local.py                    # 一键启动（校验 + 配置 + Webots）
├── team_controller.py              # 官方最小模板（直行）
├── example_controller.py           # numpy 版简单循线
└── examples/
    └── team_controller_tutorial.py # 🎓 教学版（PID 循线，有详细注释）
```

你平时只会动两个文件：

| 文件 | 用途 |
|---|---|
| `sdk/examples/team_controller_tutorial.py` | **复制一份到别处**，改成你自己的 controller |
| `sdk/rules.yaml` | 一般**不需要改**；如你自研工具链想收紧/放宽规则再调 |

---

## 5. 5 分钟快速开始

把教学版控制器复制成你的工作文件，然后一条命令跑起来。

### 5.1 复制示例 controller

把教学版复制一份到 `sdk/my_controller.py`（放在 `sdk/` 目录里便于 Webots 定位，也避免仓库根目录杂乱）：

```powershell
Copy-Item sdk/examples/team_controller_tutorial.py sdk/my_controller.py
```

> 💡 路径不是硬性要求，但**建议放在 `sdk/` 里**——仓库根路径若含中文/空格，部分 Webots 版本的 `Camera.saveImage` 会写图失败；`sdk/` 子目录本身是纯 ASCII，减少一类踩坑。

### 5.2 一键启动

```powershell
python sdk/run_local.py --code-path sdk/my_controller.py
```

这条命令会：

1. 用 `rules.yaml` 校验 `sdk/my_controller.py`
2. 生成 `.local/race_config.json`（仓库根下的 `.local/` 目录，已在 `.gitignore` 外）
3. 找到 Webots 可执行文件并启动默认赛道 `simnode/webots/worlds/track_basic.wbt`，
   分配默认车位 `car_1`（CarPhoenix，烈焰红）

启动成功后，Webots 窗口里你会看到你选中的那辆车（默认 `car_1` 是烈焰红的 CarPhoenix）按你的代码跑起来。
其它 5 个车位（`car_2` ~ `car_6`）也会启动相同的 `car` controller，但由于配置里没有它们，会立刻进入"空转"模式，不会动。

### 5.3 常用变体

```powershell
# 只做校验，不启动 Webots（CI 友好）
python sdk/run_local.py --code-path sdk/my_controller.py --validate-only

# 已经校验过了，跳过校验直接跑
python sdk/run_local.py --code-path sdk/my_controller.py --skip-validate

# 无渲染、快速模式（适合 headless / 批量测试）
python sdk/run_local.py --code-path sdk/my_controller.py --fast --minimize
```

> ⚠️ 启动后 Webots 窗口里可能一开始小车是静止的——这是正常现象，前 1~2 秒是摄像头激活与沙箱启动时间。

### 5.4 选择赛道和车型

目前 `simnode/webots/worlds/` 里有三个预置赛道，每个赛道提前摆好了若干辆不同外观的 Car PROTO（CarPhoenix、CarThunder …），你通过 `--world` 选赛道、`--car-slot` 选车位，即可指定自己被分配到哪辆车：

```powershell
# 列出所有赛道及其车位 → 车型映射
python sdk/run_local.py --list-worlds

# 选复杂赛道的 car_3（毒蛇绿 CarViper）
python sdk/run_local.py --code-path sdk/my_controller.py --world complex --car-slot car_3

# 也接受 .wbt 文件名或完整路径（向后兼容老写法）
python sdk/run_local.py --code-path sdk/my_controller.py --world track_complex.wbt --car-slot car_4
```

可用赛道（当前版本）：

| 短名 | 文件 | 简介 |
|---|---|---|
| `basic`（**默认**） | `track_basic.wbt` | 入门椭圆赛道：两条直道 + 两段大弧弯 |
| `complex` | `track_complex.wbt` | 进阶赛道：复合弯 + 发卡 + S 弯 |
| `airacer` | `airacer.wbt` | 最早的 demo 赛道（手写 Robot 节点，非 Car PROTO） |

`track_basic` / `track_complex` 的 6 个车位都一致：

| 车位 | 车型 | 颜色 |
|---|---|---|
| `car_1` | CarPhoenix | 烈焰红 |
| `car_2` | CarThunder | 电光蓝 |
| `car_3` | CarViper | 毒蛇绿 |
| `car_4` | CarNova | 新星黄 |
| `car_5` | CarFrost | 冰霜白 |
| `car_6` | CarShadow | 暗夜黑 |

> 💡 **重要**：车位的外观是赛道 `.wbt` 里写死的，**`--car-slot` 并不是"选一辆车"，而是"选择坐到哪个座位上"**；同一车位在不同赛道上可能是不同型号的车（当前 basic / complex 恰好一致，但以后换地图不一定）。SDK 会在启动前校验 `--car-slot` 是否真的存在于你选的赛道里，不存在会报错并列出可用车位。

> ⚠️ 如果你想切到某个没在 `sdk/worlds.py` 中登记的新世界文件，传完整路径（`--world /path/to/your.wbt`）也能跑起来，只是 SDK 没法再帮你做 slot 校验。

---

## 6. 编写你的控制器

### 6.1 接口契约（**严格，不要改签名**）

```python
import numpy as np

def control(
    left_img: np.ndarray,    # (480, 640, 3), uint8, BGR
    right_img: np.ndarray,   # (480, 640, 3), uint8, BGR
    timestamp: float,        # 秒
) -> tuple[float, float]:
    ...
    return steering, speed   # ∈ [-1, 1],  ∈ [0, 1]
```

### 6.2 可用库（沙箱白名单）

`numpy`, `cv2`, `math`, `collections`, `heapq`, `functools`, `itertools`, `typing`, `__future__`

其它所有模块都会被 **拒绝 import**（包括 `os`, `sys`, `time`, `socket`,
`subprocess`, `threading`, `requests`、以及 Windows 特定的 `winreg`/`nt`/`_winapi` 等）。

禁止调用内置：`open`, `eval`, `exec`, `compile`, `globals`, `locals`, `input`, `breakpoint`, `__import__`, `vars`。

禁止访问逃逸属性（validator 直接报 **E007** error）：
`__globals__`, `__builtins__`, `__subclasses__`, `__mro__`, `__code__`, `__closure__`, `func_globals`。

### 6.3 性能上限

- **单帧 20 ms** 硬上限，超时 3 次本圈作废
- validator 会跑 10 次 mock 测平均耗时，超过 14 ms 会警告

> 💡 **提速技巧**：避免每帧分配新大数组、避免 Python 循环做像素遍历，优先 numpy 向量化 / `cv2` 原生函数。

### 6.4 一个最简 PID 循线示例

完整可读版见 `sdk/examples/team_controller_tutorial.py`。里面有：

- 参数集中在文件顶部常量区，**全是你可以微调的旋钮**
- `_estimate_track_center_x`：行扫描找赛道中心
- PID 只给了 Kp/Kd，默认 Ki=0（积分容易让直道飘）
- 转向大时自动降速

建议的调参路径：
1. 先只调 `TRACK_THRESHOLD`，让黑白赛道分得干净
2. 再调 `KP`，让转弯响应及时但不振荡
3. 最后补 `KD` 抑振
4. 速度策略最后优化

---

## 7. 提交前校验

### 7.1 手动跑一次

```powershell
python sdk/validate_controller.py --code-path sdk/my_controller.py
```

输出示例：

```
正在验证: sdk/my_controller.py
  ✓ 语法检查
  ✓ 文件检查
  ✓ 禁止导入扫描
  ✓ 禁用内置扫描
  ✓ 接口验证

性能：
  mock_calls = 30
  mock_exceptions = 0
  soft_timeout_ms = 20
  avg_call_ms = 4.67
  p95_call_ms = 5.02

全部通过。
```

### 7.2 机器可读的 JSON 输出

```powershell
python sdk/validate_controller.py --code-path sdk/my_controller.py --json
```

返回结构（节选）：

```json
{
  "passed": true,
  "errors": [],
  "warnings": [
    {"code": "W004", "severity": "warn", "message": "...", "lineno": 12}
  ],
  "summary": "通过（含 1 条 warning）。",
  "meta": {
    "mock_calls": 30,
    "mock_exceptions": 0,
    "soft_timeout_ms": 20,
    "avg_call_ms": 4.67,
    "p95_call_ms": 5.02
  }
}
```

### 7.3 退出码约定

| 退出码 | 含义 |
|---|---|
| `0` | 通过（可能含 warning） |
| `1` | 存在 error，修完才能提交 |
| `2` | 校验器本身异常（rules.yaml 坏了等） |
| `3` | 启用 `--strict` 且仅有 warning |

CI 脚本里推荐 `--strict`，把 warning 也当拦截线。

### 7.4 常见错误码速查

| Code | 级别 | 含义 | 典型修法 |
|---|---|---|---|
| E001 | error | 文件过大 | 删除未用数据/注释；不要在源码里塞图像 |
| E003 | error | 语法错误 | 按报错行修 |
| E004 | error | 导入了黑名单模块 | 换成白名单内的等价实现 |
| E005 | error | 相对 import | 只能写绝对 import，且目标必须在白名单 |
| E006 | error | 调用了禁用内置（eval/open/`__import__`…） | 线上一定会被拦，老实写代码 |
| E007 | error | 访问了沙箱逃逸属性（`__globals__`/`__subclasses__` 等） | 这在线上 RESTRICTED_BUILTINS 下会失败 |
| E008 | error | 缺少 `control` 函数 | 按 6.1 定义 |
| E010 | error | 模块加载时触发非法 import | 检查顶层 import，移除黑名单项 |
| E011 | error | 模块加载失败（非 ImportError） | 看报错信息，通常是顶层代码抛异常 |
| E012 | error | 返回值格式错 | 必须 `return steering, speed` 两个 float |
| W004 | warn | 未知 import（非黑非白） | 若不是白名单内的，线上会 ImportError |
| W007 | warn | 访问了一般可疑 dunder（`__loader__`/`__spec__`/`__import__`） | 一般无需修；如你在做 meta 编程请确认 |
| W011 | warn | `control()` 调用抛异常 | 线上会捕获并回落到 (0, 0)，但仍建议修好 |
| W013 | warn | 返回值越界 | 自觉 clip 到 [-1, 1] / [0, 1] |
| W014 | warn | 耗时接近/超过 20 ms | 优化算法或减少每帧分配（看 `meta.p95_call_ms`） |

---

## 8. 常见问题 FAQ

<details>
<summary>❓ Q1：<code>run_local.py</code> 报 "未能找到 Webots 可执行文件"</summary>

A：`run_local.py` 会按以下顺序自动查找 Webots：
1. 命令行 `--webots` 参数；
2. `$WEBOTS_HOME` 环境变量（支持 Windows msys64 布局、Linux、macOS `.app`）；
3. 系统 `PATH`；
4. 各平台常见默认安装路径（Windows 会扫描所有盘符下的 `Webots\...`、`Program Files\Webots\...`、`Program Files (x86)\Webots\...`）。

通常装完 Webots 无需额外配置即可被自动发现。实在找不到的话：

```powershell
# Windows：显式指定（你的安装路径，例如非默认盘符）
python sdk/run_local.py --code-path sdk/my_controller.py --webots "E:\Webots\msys64\mingw64\bin\webotsw.exe"

# 或设环境变量一次，之后命令行不用带 --webots
$env:WEBOTS_HOME = "E:\Webots"
python sdk/run_local.py --code-path sdk/my_controller.py
```
</details>

<details>
<summary>❓ Q2：Webots 启动后小车完全不动</summary>

A：最常见三个原因：

1. **沙箱子进程起不来** — 在 Webots 控制台看红色 stderr，一般是 `control()`
   加载时抛异常，本地先 `python sdk/my_controller.py` 冒烟。

2. **Webots 使用的 Python 里没装 numpy/cv2** — Webots 会选一个 Python
   解释器启动 `sandbox_runner.py`。把它对准你日常用的 conda env：

   Windows PowerShell：
   ```powershell
   conda activate airacer       # 你的环境名
   python sdk/run_local.py --code-path sdk/my_controller.py
   ```

   Linux/macOS：
   ```bash
   conda activate airacer
   python sdk/run_local.py --code-path sdk/my_controller.py
   ```

   也可以在 Webots 菜单 *Tools → Preferences → General → Python command*
   显式填入 `/path/to/conda/envs/airacer/bin/python`（Windows 上填 `python.exe`）。

3. **`control()` 每帧超过 20 ms** — 连续 3 次超时会触发 5 秒停车惩罚。
   先用 `python sdk/validate_controller.py --code-path sdk/my_controller.py`
   看 `avg_call_ms` / `p95_call_ms`，接近 20 ms 就要优化。
</details>

<details>
<summary>❓ Q3：本地跑通了，提交服务器却被拒 / 运行中抛 ImportError</summary>

A：服务器的 `/api/submit` **不会**静态扫描你的导入，它只做
`py_compile` + 尝试 `exec_module` + 一次 mock 调用。真正拦截非法 import
的是**运行时沙箱**（`simnode/car_sandbox.py` 的 `SandboxImportHook`）——
也就是说：提交的那一刻可能通过，但线上真正跑比赛时才 ImportError。

避免这种情况的唯一办法是**本地先用 validator 扫一遍**：

```powershell
python sdk/validate_controller.py --code-path sdk/my_controller.py --strict
```

其他常见差异：

1. 服务端是 Linux，文件路径大小写敏感；
2. 服务端只装了 `numpy` + `opencv-python-headless`，没有 GUI 的 OpenCV 组件会缺；
3. Validator 只扫你的主控制器文件；如果你另外 `from helpers import foo`，
   helpers 里的非法 import 不会被扫到（线上会在 `import helpers` 那一行抛 ImportError）。
</details>

<details>
<summary>❓ Q4：我想改 rules.yaml 放宽限制</summary>

A：🚧 _占位_ —— 学生私自改 `rules.yaml` 只影响本地校验，线上沙箱不认这份 yaml。想真正拓展白名单需要向项目组提 issue。
</details>

<details>
<summary>❓ Q5：Webots 里看到的赛道在哪里定义的？怎么切换？</summary>

A：所有预置赛道都放在 `simnode/webots/worlds/` 下：

| 文件 | 短名 | 说明 |
|---|---|---|
| `track_basic.wbt` | `basic`（默认） | 入门椭圆赛道 |
| `track_complex.wbt` | `complex` | 进阶复合弯 + 发卡 + S 弯 |
| `airacer.wbt` | `airacer` | 旧版 demo 赛道（手写 Robot 节点） |

车辆 PROTO 在 `simnode/webots/protos/Car*.proto`（CarPhoenix / CarThunder / CarViper / CarNova / CarFrost / CarShadow 共 6 种外观）。

切换赛道和车位：

```powershell
python sdk/run_local.py --list-worlds    # 查看所有赛道 + 车位映射
python sdk/run_local.py --code-path sdk/my_controller.py --world complex --car-slot car_5
```

详细见 [5.4 选择赛道和车型](#54-选择赛道和车型)。最终线上比赛用的世界可能会替换，请关注项目 `CHANGELOG`。
</details>

<details>
<summary>❓ Q6：PowerShell 里 <code>python ... | Out-String</code> 输出乱码</summary>

A：PowerShell 默认用 cp936（GBK）重新解码 Python 的 UTF-8 输出。直接运行不会有问题；如果你必须 pipe，在会话开头设一次：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
```

校验器内部已自动降级逻辑：检测到 stdout 不支持 `✓/✗` 时会改用 `[OK]/[FAIL]` 标记。
</details>

<details>
<summary>❓ Q7：Webots 启动后控制台持续刷 <code>Error: could not open "...\live_view.jpg" for writing</code></summary>

A：Webots 的 C++ `Camera.saveImage()` 在 Windows 上用窄字符 `fopen`，对含**非 ASCII 字符（中文/韩文/俄文 …）的路径**会直接失败。常见诱因是仓库放在中文目录里，例如 `D:\课程\数据结构\pkudsa.airacer\`。

`sdk/make_local_config.py` 已经做了兜底：当仓库根路径含非 ASCII 字符时，`recording_path` 会自动落到 `%TEMP%\airacer_local\recordings`（Windows 的 `%TEMP%` 对非 ASCII 用户名会返回 8.3 短路径，全 ASCII）。所以**现在**直接运行 `run_local.py` 不会再报错。

如果你自定义了 `--recording-path`，请确保它**全 ASCII**：

```powershell
python sdk/run_local.py --code-path sdk/my_controller.py `
    --recording-path C:\airacer\recordings
```

根治方案是把整个仓库挪到纯 ASCII 路径（推荐 `C:\projects\pkudsa.airacer`）。
</details>

---

## 9. 反馈渠道

- Bug / 功能需求：在项目仓库提 issue
- 紧急问题：🚧 _占位_ —— 由 TA 在群公告里提供官方渠道

---

**变更日志**

| 版本 | 日期 | 改动 |
|---|---|---|
| v0.1 | 2026-05-03 | 初稿：SDK 工具链齐全后的学生侧手册 |
| v0.2 | 2026-05-05 | 将工作文件从仓库根迁到 `sdk/my_controller.py`；补充 Webots 自动发现（任意盘符）、race_config session 字段默认值、非 ASCII 路径自动兜底（%TEMP%）、FAQ Q7；Q1/Q2/Q3 命令示例统一为 `sdk/my_controller.py` |
| v0.3 | 2026-05-05 | 接入 `track_basic` / `track_complex` 新赛道与 Car 系列 PROTO（CarPhoenix … CarShadow）；新增 `sdk/worlds.py` 作为赛道/车型目录；`run_local.py` 支持 `--list-worlds`、`--world` 短名、自动校验 `--car-slot`；默认赛道改为 `basic`；新增 §5.4 选择赛道和车型；FAQ Q5 重写 |

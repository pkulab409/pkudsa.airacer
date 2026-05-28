# AI 驾驶控制器提交指南

## 1. 控制器接口规范

学生需要提交一个包含 `control()` 函数的 Python 脚本（`team_controller.py`）。

```python
import numpy as np

def control(
    left_img:  np.ndarray,   # 左摄像头图像，shape=(480, 640, 3), dtype=uint8, BGR
    right_img: np.ndarray,   # 右摄像头图像，shape=(480, 640, 3), dtype=uint8, BGR
    timestamp: float         # 当前仿真时间（秒），只读
) -> tuple[float, float]:
    """
    返回值：
        steering: float, [-1.0, 1.0]，负值左转，正值右转
        speed:    float, [0.0, 1.0]，0.0 停止，1.0 最大速度比例
    """
    steering = 0.0
    speed    = 0.5
    return steering, speed
```

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `left_img` | `np.ndarray` (480x640x3, uint8, BGR) | 左前摄像头图像 |
| `right_img` | `np.ndarray` (480x640x3, uint8, BGR) | 右前摄像头图像 |
| `timestamp` | `float`，单位秒 | 仿真已过时间 |
| 返回 `steering` | `float`，`[-1.0, 1.0]` | 方向盘转角比例 |
| 返回 `speed` | `float`，`[0.0, 1.0]` | 油门比例，`1.0` 对应实际车速 22.0 m/s（约 79 km/h） |

> **注意**：`speed` 超出 `[0.0, 1.0]` 的值会被系统自动截断，实际车速上限严格为 22.0 m/s。

---

## 2. 最小可运行模板

```python
# team_controller.py - 官方模板：直行

def control(left_img, right_img, timestamp):
    """全速前进，不转向"""
    return 0.0, 1.0
```

完整示例见 `sdk/team_controller.py` 与 `sdk/example_controller.py`。

---

## 3. 可用库（白名单）

| 允许导入 | 说明 |
|----------|------|
| `numpy` / `np` | 图像处理必备 |
| `cv2` | OpenCV 视觉处理 |
| `math` | 数学运算 |
| `collections` | 数据结构 |
| `heapq` | 优先队列 |
| `functools` | 函数工具 |
| `itertools` | 迭代工具 |
| `typing` | 类型注解 |
| `__future__` | 语法 future 声明 |
| `pathlib` | 路径操作（只读用途） |
| `dataclasses` | 数据类装饰器 |
| `re` | 正则表达式 |

**禁止导入**（包括但不限于）：`os`, `sys`, `socket`, `subprocess`, `multiprocessing`, `threading`, `time`, `datetime`, `io`, `builtins`, `ctypes`, `shutil`, `tempfile`, `glob`, `fnmatch`, `winreg`, `nt`, `_winapi`, `requests`, `urllib`, `http`, `ftplib`, `smtplib`, `signal`, `gc`, `inspect`, `importlib`, `pickle`。

**禁止使用的内置函数**：`open`, `eval`, `exec`, `globals`, `locals`, `compile`。

---

## 4. 执行限制

| 限制项 | 值 | 说明 |
|--------|-----|------|
| 内存限制（Linux） | 512 MB | `resource.setrlimit(RLIMIT_AS)` |
| CPU 时间上限（Linux） | 30 s | `resource.setrlimit(RLIMIT_CPU)` |

> **注意**：当前版本尚未对学生 `control()` 函数的单步执行时间做硬性截断。若代码死循环或耗时过长，会直接阻塞仿真步进。请确保 `control()` 能在毫秒级返回。

---

## 5. 本地验证

提交前可使用本地验证工具检查代码合规性：

```bash
python sdk/validate_controller.py --code-path my_controller.py --rules-path sdk/rules.yaml
```

验证内容：
1. Python 语法合法（`py_compile`）
2. `control` 函数是否存在且可调用
3. 禁止 import 的 AST 静态扫描
4. Mock 调用：检查返回值类型和数值范围

---

## 6. 提交方式

通过学生提交页（`/submit/`）上传 `team_controller.py`，或调用 API：

```bash
POST /api/submit
Body: {
  "team_id": "A01",
  "password": "...",
  "code": "<base64 编码的 .py 文件>",
  "slot_name": "main"   // 可选：main / dev / backup
}
```

**提交流程**：

```
上传 team_controller.py
    |
    v
即时校验（Backend，<< 2 秒）
    |-- 通过：写入文件系统 + 数据库
    |-- 失败：返回详细错误，不入库
    |
    v
手动申请测试（/api/test-request 或前端点击"申请测试"）
    |
    v
测试队列（内存 FIFO，Worker 消费）
    |-- 单车测试（SimNode 运行约 5~10 分钟）
    |
    v
测试报告（仅本队可见）
    |-- 完成圈数
    |-- 最快单圈时间
    |-- 碰撞次数（轻微/严重）
    |-- 结束原因
```

---

## 7. 三槽位与激活机制

- **main**：主力版本，默认参赛槽位
- **dev**：开发版本，用于迭代测试
- **backup**：备用版本

上传新版本到某槽位后，该槽位旧版本自动失效。需手动点击**"设为参赛"**（调用 `/api/activate`）将某个槽位标记为 `is_race_active=1`，该版本才会被用于正式比赛。

---

## 8. 提交锁定

- 赛区处于 `REGISTRATION` 状态时允许上传代码
- 管理员可执行**"锁定提交"**将赛区转入 `IDLE`，此后拒绝所有新提交（HTTP 403）
- 锁定后，各队使用最后一次成功上传的版本参赛
- 无有效提交的队伍：小车将**静止不动**（速度=0，转向=0），不会使用任何默认策略

---

**最后更新**：2026-05-20

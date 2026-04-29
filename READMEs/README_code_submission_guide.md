# AI 驾驶控制器提交指南

## 1. 控制器接口规范

学生需要提交一个包含 `control()` 函数的 Python 脚本（`team_controller.py`）。

与 Avalon 的区别：Avalon 要求实现一个 `Player` **类**（13 个方法），AiRacer 简化为**一个函数**，但设计思路完全相同。

```python
import numpy as np

def control(
    left_img:  np.ndarray,   # 左目摄像头图像，shape=(480,640,3), dtype=uint8, BGR 通道
    right_img: np.ndarray,   # 右目摄像头图像，shape=(480,640,3), dtype=uint8, BGR 通道
    timestamp: float         # 当前仿真时间（秒），只读
) -> tuple[float, float]:
    """
    返回值：
        steering: float, [-1.0, 1.0]，负值左转，正值右转
        speed:    float, [0.0, 1.0]，0.0 停止，1.0 最大速度
    执行时限：20ms / 次（对应 Avalon 的方法调用超时限制）
    """
    steering = 0.0
    speed    = 0.5
    return steering, speed
```

### 参数说明

| 参数 | 类型 | Avalon 类比 | 说明 |
|------|------|-------------|------|
| `left_img` | `np.ndarray` (480×640×3, uint8, BGR) | `pass_role_sight()` 传入的视野 | 左前摄像头图像 |
| `right_img` | `np.ndarray` (480×640×3, uint8, BGR) | — | 右前摄像头图像 |
| `timestamp` | `float`，单位秒 | `pass_position_data()` 中的时间 | 仿真已过时间 |
| 返回 `steering` | `float`，`[-1.0, 1.0]` | `walk()` 返回方向 | 方向盘转角 |
| 返回 `speed` | `float`，`[0.0, 1.0]` | 动作力度 | 油门比例 |

---

## 2. 最小可运行模板（对应 Avalon `basic_player.py`）

```python
# team_controller.py — 官方模板：直行

def control(left_img, right_img, timestamp):
    """全速前进，不转向"""
    return 0.0, 1.0
```

完整版本见 `sdk/team_controller.py`。

---

## 3. 可用库（对应 Avalon `restrictor.py` 白名单）

| 允许导入 | 说明 |
|----------|------|
| `numpy` | 图像处理必备 |
| `cv2` | OpenCV 视觉处理 |
| `math` | 数学运算 |
| `collections` | 数据结构（deque 等） |
| `heapq` | 优先队列 |
| `functools` | 函数工具 |
| `itertools` | 迭代工具 |

禁止导入：`os`, `sys`, `socket`, `subprocess`, `threading`, `time`, `requests` 及所有系统/网络模块。

禁止使用：`open`, `eval`, `exec`, `globals`, `locals`。

---

## 4. 执行限制（对应 Avalon 方法调用超时）

| 限制项 | 值 | 说明 |
|--------|-----|------|
| 单步执行时限 | 20ms | 超时沿用上一帧指令 |
| 连续超时次数 | 3 次 | 该圈计圈无效 |
| 内存限制（Linux） | 512 MB | `resource.setrlimit` 强制 |
| CPU 时间上限（Linux） | 30s/race | 防止无限循环导致占用 |

---

## 5. 本地验证（对应 Avalon 代码合规检查）

在提交前，可使用提供的本地验证工具检查代码是否通过平台校验：

```bash
python sdk/validate_controller.py --code-path my_controller.py
```

验证内容：

1. Python 语法合法（`py_compile`）
2. `control` 函数是否存在且可调用
3. 禁止 import 的 AST 静态扫描
4. Mock 调用：检查返回值类型和数值范围

---

## 6. 提交方式

通过学生提交页（`/submit/`）上传 `team_controller.py`。

**提交流程（与 Avalon 代码管理完全类似）：**

```
上传 team_controller.py
    │
    ▼
即时检查（Backend，< 2 秒）
    ├── 通过：写入数据库，加入测试队列
    └── 失败：返回详细错误，不入队
    │
    ▼
测试队列（对应 Avalon BattleManager 队列）
    └── 单车测试（占用 Sim Node 约 5~10 分钟）
    │
    ▼
测试报告（仅本队可见）
    ├── 是否完成 2 圈
    ├── 最快单圈时间
    ├── 碰撞次数（轻微/严重）
    ├── 超时警告次数
    └── 测试结束原因
```

---

## 7. 提交锁定

- 助教执行锁定指令后，平台立即停止接受新提交
- 不可逆，请在截止前确认提交
- 锁定后，各队使用截止前最后一次通过检查的版本
- 无有效提交的队伍使用官方模板（直行，`return 0.0, 1.0`）

---

**最后更新**：2026-04-28

# AI Racer 平台架构设计文档

> 2026年春季数算B大作业  
> 版本 v0.5 | 2026-04-10

---

## 一、赛事规则设计

### 1.1 参赛规模与场次约束

- 参赛队伍数量：约25组（以实际报名数为准）
- 每场仿真同时运行车辆数：2~4辆
- 所有比赛在同一台中心机器上运行，同一时刻只运行一个 Webots 仿真实例

### 1.2 赛制结构

赛制分为四个阶段，按顺序执行：

```
排位赛（全员，共7批次，每批3~4队，各自独立计时）
    │
    ├─ 按排位成绩 1~25 名进行蛇形分组
    ▼
分组赛（共7场，每场3~4队，同场竞速）
    │
    ├─ 各场第1名（共7队）+ 排位成绩最快的第2名（共1队）= 8队晋级
    ▼
半决赛（共2场，每场4队，同场竞速）
    │
    ├─ 每场前2名晋级，共4队进入决赛
    ▼
决赛（1场，4队，同场竞速）
```

**各阶段说明：**

| 阶段 | 场次数 | 每场车辆数 | 固定圈数 | 预计耗时 | 说明 |
|------|--------|------------|----------|----------|------|
| 排位赛 | 7批 | 3~4辆 | 2圈（计时） | 约35分钟 | 各车独立计时，取2圈内最快单圈；同批次车辆之间不存在竞争关系，各自成绩独立记录 |
| 分组赛 | 7场 | 3~4辆 | 3圈 | 约35分钟 | 竞速赛制，先完成3圈者获胜（见1.4节） |
| 半决赛 | 2场 | 4辆/场 | 3圈 | 约12分钟 | 竞速赛制，每场前2名晋级决赛 |
| 决赛 | 1场 | 4辆 | 5圈 | 约8分钟 | 竞速赛制，圈数多于其他阶段 |
| 合计 | — | — | — | 约1.5小时 | 含场间 Webots 重启和代码加载时间（约2~3分钟/场）|

### 1.3 蛇形种子分组规则

排位赛结束后，按排位成绩对25队从1到25排序，按以下蛇形规则分配至7个分组（前4组各4队，后3组各3队）：

```
第1轮分配（正序）：名次 1 → G1，2 → G2，3 → G3，4 → G4
第2轮分配（反序）：名次 5 → G4，6 → G3，7 → G2，8 → G1
第3轮分配（正序）：名次 9 → G1，10 → G2，11 → G3，12 → G4
...以此类推
```

最终各组成员示例（25队）：

| 组别 | 成员排位名次 |
|------|------------|
| G1 | 1, 8, 9, 16, 17 |
| G2 | 2, 7, 10, 15, 18 |
| G3 | 3, 6, 11, 14, 19 |
| G4 | 4, 5, 12, 13, 20 |
| G5 | 21, 24, 25 |
| G6 | 22, 23（+ 可并入G5或G7）|
| G7 | 视实际人数调整 |

> 注：最终分组人数视实际报名数调整

### 1.4 竞速赛制与排名规则

#### 排名赛（分组赛 / 半决赛 / 决赛）

**比赛结束条件：**
1. 本场第一辆车完成规定圈数并经过终点线，Supervisor 记录该时刻的仿真时间，启动60秒宽限计时
2. 宽限期内完成规定圈数的车辆，记录各自的完赛时间（从比赛开始到经过终点线的仿真时间差）
3. 宽限期（60秒）结束后，比赛正式结束，Supervisor 向后端推送 `race_end` 事件

**排名规则（优先级从高到低）：**
1. 在宽限期内完成规定圈数的车辆，按完赛时间升序排列（完赛时间短者排名靠前）
2. 宽限期结束时仍未完成规定圈数的车辆，按已完成圈数降序排列；圈数相同时按 `lap_progress` 降序排列；所有未完赛车辆排在已完赛车辆之后

**各阶段规定圈数：**

| 阶段 | 规定圈数 |
|------|----------|
| 分组赛 | 3圈 |
| 半决赛 | 3圈 |
| 决赛 | 5圈 |

#### 排位赛

- 赛制为计时赛，不设固定比赛结束条件，每辆车最多完成2圈后停止
- 每队成绩取2圈内的**最快单圈时间**
- 未完成任意一圈的队伍，排位成绩记为 DNF，排在已完成队伍之后，DNF 队伍内部按 `lap_progress` 降序排列

### 1.5 晋级规则

- 分组赛各场第1名自动晋级半决赛（共7名）
- 剩余一个半决赛席位由所有分组赛第2名中、排位赛成绩最快者获得（wild card制）
- 半决赛各场前2名晋级决赛（共4名）
- 未晋级队伍不参与半决赛和决赛，其成绩以分组赛最终排名为准

---

## 二、系统总体架构

### 2.1 部署环境

- 运行平台：单台 Linux 机器（中心机器）
- 局域网内所有设备均可通过浏览器访问前端
- 同一时刻只运行一个 Webots 仿真实例（比赛与测试不并行）

### 2.2 三层架构

```
┌──────────────────────────────────────────────────────────────┐
│                         中心机器 (Linux)                      │
│                                                              │
│  ┌──────────────────────────┐   ┌──────────────────────────┐ │
│  │      Layer 1             │   │        Layer 2            │ │
│  │   Webots 仿真层           │TCP│    赛事管理后端            │ │
│  │                          │◄─►│    (Python / FastAPI)    │ │
│  │  airacer.wbt             │   │                          │ │
│  │  supervisor.py           │   │  race/state_machine.py   │ │
│  │  car_controller.py       │   │  race/ipc.py             │ │
│  │  sandbox_runner.py       │   │  race/scoring.py         │ │
│  │                          │   │  race/session.py         │ │
│  │                          │   │  api/submission.py       │ │
│  │                          │   │  ws/broadcaster.py       │ │
│  └──────────────────────────┘   └──────────┬───────────────┘ │
│  Webots Web Stream (port 1234)              │ WebSocket       │
│           │                                │ REST API        │
└───────────┼────────────────────────────────┼─────────────────┘
            │                                │
            ▼                                ▼
┌──────────────────────────────────────────────────────────────┐
│                    Layer 3：前端（浏览器访问）                  │
│                                                              │
│  /race   大屏比赛页（Webots串流 + 2D小地图 + 排行榜）          │
│  /submit 学生代码提交页（上传 + 测试状态查询）                  │
│  /admin  助教控制台（赛程控制 + 积分总览）                      │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 各层模块职责

#### Layer 1 — Webots 仿真层

| 模块 | 文件路径 | 职责描述 |
|------|----------|----------|
| 世界文件 | `webots/worlds/airacer.wbt` | 定义赛道几何、车辆节点、障碍物初始布置、光照、物理参数 |
| Supervisor 控制器 | `webots/controllers/supervisor/supervisor.py` | 拥有场景树特权访问权限；负责计圈判定、竞速赛制比赛结束逻辑（领先者完赛→60秒宽限→推送 race_end）、碰撞检测、动态障碍生成与销毁、加速包生成与销毁、比赛状态数据推送 |
| 车辆控制器框架 | `webots/controllers/car/car_controller.py` | 在 Webots 进程内运行；每仿真步读取双目摄像头图像，传入对应队伍的沙箱子进程，接收 steering/speed 后施加到车辆 Driver 接口；处理超时与崩溃恢复 |
| 沙箱执行器 | `webots/controllers/car/sandbox_runner.py` | 作为独立子进程运行；加载并执行学生的 `control()` 函数；启动时施加 Linux 资源限制 |

#### Layer 2 — 赛事管理后端

| 模块 | 文件路径 | 职责描述 |
|------|----------|----------|
| 主入口 | `server/main.py` | FastAPI 应用初始化，挂载所有 HTTP 路由和 WebSocket 端点 |
| 赛事状态机 | `server/race/state_machine.py` | 维护当前赛事阶段（IDLE / QUALIFYING / GROUP_RACE / SEMI / FINAL 等），控制状态合法流转，拒绝非法跳步操作 |
| 会话管理 | `server/race/session.py` | 通过 `subprocess` 启动和终止 Webots 进程；写入每场比赛的配置文件；监控 Webots 进程存活状态 |
| IPC 通信 | `server/race/ipc.py` | 监听本地 TCP Socket（端口9100），接收 Supervisor 每仿真步推送的状态 JSON，解析后分发给计分引擎和 WebSocket 广播器 |
| 计分引擎 | `server/race/scoring.py` | 根据 IPC 接收的事件实时维护各队圈数、用时、碰撞次数、加速包拾取次数；计算场内实时排名；比赛结束后写入数据库 |
| WebSocket 广播器 | `server/ws/broadcaster.py` | 维护所有已连接的前端 WebSocket 客户端列表；以约30Hz频率向所有客户端推送当前比赛状态；关键事件（计圈、碰撞等）触发即时推送 |
| 提交 API | `server/api/submission.py` | 接收学生代码上传请求；执行语法检查和接口合规检查；通过检查后写入文件系统和数据库，加入测试队列 |
| 测试队列管理 | `server/api/testqueue.py` | 维护 FIFO 测试队列；比赛期间暂停消费；顺序启动 Webots 单车测试实例；记录测试结果 |
| 助教 API | `server/api/admin.py` | 提供赛程控制接口（开始/停止比赛、提交锁定、场次配置等）；需密码验证 |
| 数据库 | `server/db/models.py` | SQLite 数据库模型定义（队伍、提交记录、测试记录、比赛场次、积分） |

#### Layer 3 — 前端

| 页面 | 访问路由 | 访问对象 | 主要功能 |
|------|----------|----------|----------|
| 大屏比赛页 | `/race/` | 所有观众（投影展示） | 嵌入 Webots 3D 串流、2D 小地图、实时排行榜、车辆状态、事件提示 |
| 代码提交页 | `/submit/` | 参赛学生 | 队伍登录、代码上传、即时检查结果展示、测试队列状态、历史提交记录与测试报告 |
| 助教控制台 | `/admin/` | 助教 | 赛程推进控制、提交锁定、分组赛对阵确认与调整、积分总览 |

---

## 三、关键接口规范

### 3.1 学生代码接口（team_controller.py）

学生提交唯一文件 `team_controller.py`，该文件必须包含以下函数，签名不可修改：

```python
import numpy as np

def control(left_img: np.ndarray,
            right_img: np.ndarray,
            timestamp: float) -> tuple[float, float]:
    """
    参数：
        left_img:  左目摄像头图像
                   shape = (480, 640, 3), dtype = uint8, 通道顺序 BGR
        right_img: 右目摄像头图像
                   shape = (480, 640, 3), dtype = uint8, 通道顺序 BGR
        timestamp: 当前仿真时间，单位秒（float）
                   此参数为只读参考值，禁止基于此参数实现帧间计时逻辑

    返回值：
        steering: float，范围 [-1.0, 1.0]
                  负值表示向左转向，正值表示向右转向，0.0 表示直行
        speed:    float，范围 [0.0, 1.0]
                  表示目标速度相对于当前最大速度的比例
                  0.0 表示停止，1.0 表示以当前允许最大速度行驶

    函数执行时限：每次调用必须在 20ms 内返回
    """
    steering = 0.0
    speed = 0.5
    return steering, speed
```

**沙箱中禁止执行的操作（运行时强制限制，违反则终止进程）：**

| 禁止内容 | 具体限制 |
|----------|----------|
| 系统调用 | 禁止 `import os, sys, socket, subprocess, multiprocessing, threading` |
| 文件操作 | 禁止任何文件读写（`open()` 等），`RLIMIT_FSIZE = 0` |
| 网络访问 | 子进程运行于独立 network namespace，无法访问任何网络接口 |
| 子进程创建 | `RLIMIT_NPROC = 0`，禁止 fork |
| 阻塞调用 | 禁止 `time.sleep()`，禁止 `import time, datetime` |
| 场景树访问 | 不在 Webots 控制器进程内，无法访问 Webots API |

**允许使用的标准库/第三方库（预装于运行环境）：**
`numpy`, `cv2`（OpenCV）, `math`, `collections`, `heapq`, `functools`, `itertools`

### 3.2 Supervisor → 后端 IPC 数据格式

- 连接方式：Supervisor 作为 TCP 客户端，连接 `localhost:9100`（后端监听）
- 编码：UTF-8 JSON，每条消息以换行符 `\n` 结束
- 推送频率：每仿真步一次（仿真步长为64ms，即约15条/秒）

```json
{
  "sim_time": 45.312,
  "cars": [
    {
      "team_id": "A01",
      "x": 12.4,
      "y": -3.1,
      "heading": 1.57,
      "speed": 8.3,
      "lap": 2,
      "lap_progress": 0.73,
      "status": "normal",
      "boost_remaining": 0.0
    }
  ],
  "events": [
    {
      "type": "lap_complete",
      "team_id": "A01",
      "lap_time": 43.21,
      "lap_number": 2
    },
    {
      "type": "collision",
      "team_id": "B02",
      "severity": "minor",
      "collision_with": "obstacle"
    },
    {
      "type": "powerup_pick",
      "team_id": "C03",
      "powerup_id": "p_04",
      "effect_duration": 2.0
    },
    {
      "type": "timeout_warn",
      "team_id": "D01",
      "warn_count": 2
    },
    {
      "type": "obstacle_spawn",
      "obstacle_id": "dyn_07",
      "x": 5.1,
      "y": 2.3
    }
  ]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `sim_time` | float | 当前仿真时间（秒），从本场比赛开始时重置为0 |
| `cars[].team_id` | string | 队伍唯一标识符 |
| `cars[].x`, `y` | float | 车辆在世界坐标系中的位置（米） |
| `cars[].heading` | float | 车辆朝向角，单位弧度，范围 [-π, π]；定义见第十一节 |
| `cars[].speed` | float | 当前车速（m/s） |
| `cars[].lap` | int | 已完成的整圈数（每次触发 `lap_complete` 事件时+1） |
| `cars[].lap_progress` | float | 当前圈内进度，取值 {0.00, 0.25, 0.50, 0.75}；定义见第十一节 |
| `cars[].status` | string | `"normal"` / `"stopped"` / `"disqualified"`，定义见第十一节 |
| `cars[].boost_remaining` | float | 加速效果剩余时间（秒），0.0表示无加速 |
| `events` | array | 本仿真步内发生的所有事件列表，可为空数组 |

### 3.3 后端 → 前端 WebSocket 推送格式

- 监听地址：`ws://localhost:8000/ws/race`
- 推送方式：后端主动推送，无需客户端轮询
- 常规推送频率：约30Hz（独立定时器驱动，与仿真步长解耦）
- 即时推送：`lap_complete`、`collision`、`powerup_pick`、`race_start`、`race_end` 类型事件发生时立即推送，不等待下一个30Hz周期

```json
{
  "type": "race_state",
  "session_id": "group_race_3",
  "session_type": "group_race",
  "phase": "running",
  "sim_time": 45.312,
  "cars": [
    {
      "team_id": "A01",
      "team_name": "队伍A",
      "x": 12.4,
      "y": -3.1,
      "heading": 1.57,
      "speed": 8.3,
      "lap": 2,
      "lap_progress": 0.73,
      "status": "normal",
      "boosted": false
    }
  ],
  "rankings": [
    {
      "rank": 1,
      "team_id": "A01",
      "team_name": "队伍A",
      "lap": 2,
      "total_time": 88.4,
      "gap_to_leader": 0.0
    },
    {
      "rank": 2,
      "team_id": "C03",
      "team_name": "队伍C",
      "lap": 2,
      "total_time": 89.1,
      "gap_to_leader": 0.7
    }
  ],
  "events": [
    {
      "type": "lap_complete",
      "team_id": "A01",
      "lap_time": 43.21,
      "lap_number": 2
    }
  ]
}
```

**`phase` 字段可能的取值：**

| 值 | 含义 |
|----|------|
| `"waiting"` | 已配置本场次，等待助教下达开始指令 |
| `"running"` | 比赛进行中 |
| `"finished"` | 本场比赛已结束，数据保留 |
| `"aborted"` | 比赛被助教手动终止 |

### 3.4 后端 → Webots 比赛配置

每场比赛开始前，后端写入 `race_config.json`，车辆控制器和 Supervisor 在启动时读取：

```json
{
  "session_id": "group_race_3",
  "session_type": "group_race",
  "total_laps": 3,
  "cars": [
    {
      "car_node_id": "car_1",
      "team_id": "A01",
      "code_path": "/submissions/A01/20260410_153021/team_controller.py",
      "start_position": 1
    },
    {
      "car_node_id": "car_2",
      "team_id": "C03",
      "code_path": "/submissions/C03/20260410_162845/team_controller.py",
      "start_position": 2
    }
  ]
}
```

---

## 四、赛事状态机

后端 `state_machine.py` 维护全局赛事状态，所有状态转换必须由助教通过 `/admin` API 触发，禁止自动跳转（除 `RACE_FINISHED` → `RACE_IDLE`）。

```
IDLE
  │ POST /api/admin/set-session  (session_type=qualifying, batch=N)
  ▼
QUALIFYING_READY
  │ POST /api/admin/start-race
  ▼
QUALIFYING_RUNNING  ─── Webots 运行中，Supervisor 推送数据
  │ Webots 进程结束 或 POST /api/admin/stop-race
  ▼
QUALIFYING_FINISHED  ─── 本批次成绩写入数据库
  │ 所有批次完成后：POST /api/admin/finalize-qualifying
  ▼
QUALIFYING_DONE  ─── 排位成绩排序完毕，蛇形分组计算完毕
  │ POST /api/admin/set-session  (session_type=group_race, session_id=G1)
  ▼
GROUP_RACE_READY
  │ POST /api/admin/start-race
  ▼
GROUP_RACE_RUNNING
  │ 结束
  ▼
GROUP_RACE_FINISHED  ─── 写入积分
  │ （重复 7 次后：POST /api/admin/finalize-group）
  ▼
GROUP_DONE  ─── 8强名单确定
  │ POST /api/admin/set-session  (session_type=semi, session_id=SF1)
  ▼
SEMI_READY → SEMI_RUNNING → SEMI_FINISHED
  │ （重复 2 次后：POST /api/admin/finalize-semi）
  ▼
SEMI_DONE  ─── 4强名单确定
  │ POST /api/admin/set-session  (session_type=final)
  ▼
FINAL_READY → FINAL_RUNNING → FINAL_FINISHED
  │ POST /api/admin/close-event
  ▼
CLOSED  ─── 所有结果已持久化，前端展示最终排名
```

**状态机约束：**
- 非法状态跳转（如从 `QUALIFYING_RUNNING` 直接跳到 `FINAL_READY`）返回 HTTP 400
- `QUALIFYING_RUNNING` / `GROUP_RACE_RUNNING` / `SEMI_RUNNING` / `FINAL_RUNNING` 状态下，测试队列暂停消费
- 任意 `*_RUNNING` 状态下，`POST /api/admin/stop-race` 强制终止 Webots 进程，进入对应 `*_FINISHED` 状态，该场成绩按当前时刻数据记录

---

## 五、沙箱安全实现

### 5.1 进程结构

```
car_controller.py (运行于 Webots 进程内，每辆车一个控制器实例)
    │
    └── subprocess.Popen(sandbox_runner.py, team_id=A01)
            │  stdin:  序列化后的图像数据（每帧约600KB二进制）
            │  stdout: 控制输出 JSON {"steering": 0.1, "speed": 0.8}\n
            │  stderr: 错误信息（仅用于日志，不影响控制流）
            └── 施加 OS 级资源限制（见5.2节）
```

每辆参赛车辆对应一个独立 `sandbox_runner.py` 子进程。进程在本场比赛开始时创建，比赛结束时终止。

### 5.2 Linux 资源限制

在 `sandbox_runner.py` 子进程内、加载学生代码前，调用以下限制：

```python
import resource, os

def apply_sandbox_limits():
    # 内存地址空间上限：512MB
    resource.setrlimit(resource.RLIMIT_AS,
                       (512 * 1024 * 1024, 512 * 1024 * 1024))
    # CPU 时间上限：10秒（进程级累计，防止无限死循环）
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    # 最大可创建子进程数：0（禁止 fork）
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    # 最大可写文件大小：0字节（禁止写文件）
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
```

网络命名空间隔离在 `Popen` 的 `preexec_fn` 中执行：

```python
import subprocess, os

proc = subprocess.Popen(
    ["python3", "sandbox_runner.py", "--team-id", team_id,
     "--code-path", code_path],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    preexec_fn=lambda: (
        os.unshare(0x40000000),  # CLONE_NEWNET：创建独立网络命名空间
        apply_sandbox_limits()
    )
)
```

### 5.3 超时处理

`car_controller.py` 在等待子进程返回控制值时，施加 20ms 超时：

| 情况 | 处理方式 |
|------|----------|
| 单次超时（未在20ms内返回） | 沿用上一帧的 steering/speed 值；向 Supervisor 发送 `timeout_warn` 事件；警告计数+1 |
| 同一队伍累计3次警告 | 向 Supervisor 发送 `lap_void` 事件；Supervisor 将该车重置至最近检查点；该圈成绩不计 |
| 子进程崩溃（`stdout` 关闭或进程退出） | `car_controller.py` 自动重启子进程；车辆停止2秒等待重启完成；向 Supervisor 发送 `process_restart` 事件 |
| 子进程触发非法系统调用（内核 SIGSYS 信号）| 子进程被终止；`car_controller.py` 检测到进程退出，不重启；向 Supervisor 发送 `disqualified` 事件；该场比赛该队判负 |

---

## 六、赛道设计规范

### 6.1 赛道几何参数

| 参数 | 规格 |
|------|------|
| 形状 | 闭合环形，行驶方向为顺时针 |
| 参考周长 | 150~200m（Webots 世界坐标单位：米） |
| 主赛道宽度 | 6~8m |
| 窄道区宽度 | 4~5m |
| 最小弯道内径 | 8m |
| 地面材质颜色 | 深灰色，RGB 约 (60, 60, 60)，使用 asphalt 材质 |

### 6.2 必须包含的路段

以下路段必须出现在赛道中，顺序和相对位置由建模人员决定：

| 路段 | 数量 | 规格 |
|------|------|------|
| 主直道 | 1段 | 长40~50m，宽8m；起终点线设于此路段；此处也是起跑格位区域 |
| 高速弯道 | 2处 | 弯道内径15m以上；车辆无需大幅减速即可通过 |
| 发夹弯 | 1~2处 | 弯道内径8~10m；车辆需减速至较低速度才能通过 |
| S型连续弯 | 1处 | 由3~4个连续反向弯道组成；每个子弯道内径不小于10m |
| 窄道区 | 1段 | 宽4~5m，长20m；两侧设置黄色路障（见6.4节） |

### 6.3 车道标线规范

所有标线颜色须与深灰色赛道底色形成高对比度，保证在640×480摄像头图像中可被颜色阈值方法分割。

| 标线 | 位置 | 颜色 | 宽度 | 样式 |
|------|------|------|------|------|
| 左侧边线 | 赛道左边界内侧0.1m | 白色 RGB(255,255,255) | 0.1m | 连续实线 |
| 中心线 | 赛道中央 | 白色 RGB(255,255,255) | 0.08m | 虚线（1m实/1m虚）|
| 右侧边线 | 赛道右边界内侧0.1m | 黄色 RGB(255,220,0) | 0.1m | 连续实线 |
| 路肩纹 | 赛道边界外侧，宽0.5m | 红白相间 | 0.25m/段 | 锯齿纹 |
| 起终点线 | 主直道中段 | 红白横纹 | 覆盖全赛道宽度 | 实线横条 |

**光照要求：**
- 使用固定白天方向光，光源方向和强度在比赛配置中固定，不随时间变化
- 禁止使用动态阴影（Webots 中关闭 `castShadows`），防止阴影遮盖标线

### 6.4 障碍物规格

#### 静态障碍（世界文件中预置，Supervisor 不移动）

| 类型 | 颜色 | 尺寸 | 默认布置位置 |
|------|------|------|------------|
| 红色锥桶 | RGB(220, 30, 30) | 高0.30m，底部直径0.20m，圆锥形 | 发夹弯入口两侧，间隔2m排列 |
| 黄色路障 | RGB(255, 220, 0)（主体），RGB(0,0,0)（条纹）| 高0.25m，宽0.40m，长0.20m，长方体 | 窄道区两侧边界，每隔3m一个 |
| 灰色石块 | RGB(100, 100, 100) | 不规则多边形体，外接球半径约0.15~0.20m | 主直道外侧路肩，每条直道不超过2个 |

所有静态障碍须完全在摄像头视野可见范围内，障碍物底面与赛道地面贴合，无悬空或嵌入地面情况。

#### 动态障碍（Supervisor 在比赛中运行时生成/删除）

| 参数 | 规格 |
|------|------|
| 类型名称 | 橙色临时锥桶 |
| 颜色 | RGB(255, 140, 0)，与静态红色锥桶形状相同 |
| 生成规则 | 每隔30秒在预定义的候选位置集合中随机选取一个位置生成一个 |
| 删除规则 | 车辆与其发生碰撞后立即删除，10秒后重新生成；或 Supervisor 手动清场时删除 |
| 同时存在上限 | 3个 |
| 禁止生成位置 | 弯道顶点前后各5m范围内；起终点线前后各20m范围内；当前已有车辆所在位置半径3m内 |
| 候选位置 | 由建模人员在世界文件中以注释标注不少于10个候选坐标点，Supervisor 从中随机选取 |

### 6.5 加速包规格

| 参数 | 规格 |
|------|------|
| 几何形状 | 扁平圆柱体，半径0.20m，高0.10m，底面悬浮于地面0.05m处 |
| 主体颜色 | 亮蓝色 RGB(0, 150, 255) |
| 动态效果 | 顶部附加白色半透明圆环，每仿真步旋转5° |
| 数量 | 赛道上同时存在2~3个 |
| 候选位置 | 由建模人员预设不少于6个固定候选位置（建议位于主直道中段及高速弯出口处）|
| 激活规则 | 每次比赛开始时随机从候选位置中选取2~3个激活；被拾取后立即消失，3秒后在另一候选位置重新生成 |
| 拾取判定 | 车辆中心点进入加速包圆柱体碰撞框时，Supervisor 判定为拾取 |
| 拾取效果 | 车辆当前最大速度提升30%，持续2秒；拾取后冷却5秒内对同一车辆不触发效果 |

### 6.6 检查点与计圈判定

赛道上均匀设置4个隐形检查区域（以 Webots 中的 `TouchSensor` 或坐标距离判定实现）：

| 检查点 | 位置 |
|--------|------|
| CP0 | 起终点线（计圈触发点） |
| CP1 | 主直道末端入弯前 |
| CP2 | 发夹弯出口 |
| CP3 | S型弯中部 |

**计圈规则：**
- Supervisor 为每辆车维护一个检查点序列状态，初始为等待CP0
- 车辆依次经过 CP0 → CP1 → CP2 → CP3 → CP0，且每段均向前行驶（heading 方向与赛道方向夹角小于90°），才计为完整一圈
- 若车辆跳过任意检查点（如倒车绕过），对应圈不计
- 每次经过CP0且前序检查点序列完整，则 `lap` 计数+1，记录本圈用时

### 6.7 碰撞判定规则

Supervisor 通过 Webots 的 `TouchSensor` 或 `ContactPoint` API 检测碰撞。

| 碰撞级别 | 判定条件 | 处理操作 |
|----------|----------|----------|
| 轻微碰撞 | 车辆与障碍物接触时相对速度 < 3 m/s，或车辆之间侧面轻微接触 | 被碰车辆速度降至当前速度的70%，持续1秒；Supervisor 推送 `collision(severity=minor)` 事件 |
| 严重碰撞 | 车辆与障碍物接触时相对速度 ≥ 3 m/s，或正面碰撞其他车辆 | 被碰车辆停止2秒；Supervisor 推送 `collision(severity=major)` 事件 |
| 判负 | 同一场次内同一队伍累计发生严重碰撞3次 | Supervisor 将该车标记为 `disqualified`，车辆停止行驶直至本场比赛结束；不计入本场排名 |

---

## 七、代码提交与模拟测试系统

### 7.1 提交流程

```
学生上传 team_controller.py
    │
    ▼
即时检查（在后端完成，目标耗时 < 2秒）
    ├── 步骤1：Python 语法检查（py_compile.compile()）
    ├── 步骤2：接口合规检查
    │         - 能否正常 import 该文件
    │         - 是否存在名为 control 的可调用对象
    │         - 调用 control(dummy_left, dummy_right, 0.0) 是否返回长度为2的 tuple
    │         - 返回值第一个元素是否为 float 且在 [-1.0, 1.0] 内
    │         - 返回值第二个元素是否为 float 且在 [0.0, 1.0] 内
    └── 通过：写入 submissions/{team_id}/{timestamp}/team_controller.py
             写入数据库 submissions 表
             加入测试队列尾部
        失败：返回错误类型和具体描述（如"第14行 SyntaxError"）
             不写入数据库，不入队列

    │（通过后）
    ▼
测试队列（FIFO，串行执行）
    ├── 当前无比赛（state_machine 不处于 *_RUNNING 状态）：自动执行队列头部任务
    ├── 当前有比赛进行中：队列暂停，比赛结束后自动恢复
    ├── 若同一队伍在队列中已有一条等待中的任务，且新提交到来：替换队列中的旧任务
    │   （如旧任务已开始执行则不替换，等当前执行完毕后，新任务作为独立条目入队）
    └── 每次执行：启动 Webots 单车实例 → 运行2圈或最多5分钟 → 关闭 Webots → 写入报告

    │
    ▼
测试报告
    ├── 是否完成2圈（bool）
    ├── 最快单圈时间（秒，未完成则为 null）
    ├── 碰撞次数（轻微/严重分别统计）
    ├── 超时警告次数
    ├── 测试结束原因（"completed" / "timeout" / "crashed" / "disqualified"）
    └── 报告仅该队伍登录后可见，其他队伍无法访问
```

### 7.2 代码截止与锁定

- 截止时间由助教在管理控制台中设置（具体时间在赛前与任课教师确认）
- 助教执行 `POST /api/admin/lock-submissions` 后，系统立即停止接收所有新提交
- 锁定操作不可逆，仅可由助教通过管理控制台触发，需二次确认
- 锁定后，每支队伍参赛使用的代码版本为截止前最后一次通过检查并入库的版本
- 若某队伍截止时无有效提交，使用官方提供的默认模板代码参赛（该代码仅实现直行，不具备视觉功能）

---

## 八、目录结构

```
airacer/
├── webots/
│   ├── worlds/
│   │   └── airacer.wbt                  # Webots 世界文件
│   ├── controllers/
│   │   ├── supervisor/
│   │   │   └── supervisor.py            # Supervisor 控制器
│   │   └── car/
│   │       ├── car_controller.py        # 车辆控制器框架
│   │       └── sandbox_runner.py        # 学生代码沙箱执行器（子进程）
│   └── protos/
│       ├── RaceCar.proto                # 赛车模型（含双目摄像头）
│       ├── TrafficCone.proto            # 锥桶（红色/橙色通过颜色参数区分）
│       ├── Barrier.proto                # 路障（黄黑色）
│       └── Powerup.proto                # 加速包（蓝色圆柱+旋转光环）
│
├── server/
│   ├── main.py                          # FastAPI 应用入口
│   ├── race/
│   │   ├── state_machine.py             # 赛事状态机
│   │   ├── session.py                   # Webots 进程启动/停止管理
│   │   ├── scoring.py                   # 实时计分逻辑
│   │   └── ipc.py                       # TCP Socket 接收 Supervisor 数据
│   ├── api/
│   │   ├── submission.py                # 代码提交与检查 API
│   │   ├── testqueue.py                 # 测试队列管理 API
│   │   └── admin.py                     # 助教控制 API
│   ├── ws/
│   │   └── broadcaster.py               # WebSocket 广播管理
│   └── db/
│       └── models.py                    # SQLite 数据模型定义
│
├── frontend/
│   ├── race/
│   │   ├── index.html                   # 大屏比赛展示页
│   │   ├── minimap.js                   # 2D 小地图渲染模块
│   │   └── leaderboard.js               # 排行榜与事件提示模块
│   ├── submit/
│   │   └── index.html                   # 学生代码提交页
│   └── admin/
│       └── index.html                   # 助教控制台页
│
├── submissions/                         # 学生代码存储目录
│   └── {team_id}/
│       └── {YYYYMMDD_HHMMSS}/
│           └── team_controller.py
│
├── race_config.json                     # 当前场次配置（后端写入，控制器读取）
│
└── template/
    └── team_controller.py               # 官方默认模板（用于无提交队伍）
```

---

## 九、双目摄像头参数

| 参数 | 取值 |
|------|------|
| 图像分辨率 | 640 × 480 像素 |
| 图像格式 | uint8，通道顺序 BGR（Webots 原生输出 RGB，控制器框架转换后传入学生代码）|
| 帧率 | 与仿真步长同步，每步输出一帧（仿真步长64ms，约15帧/秒）|
| 水平视场角（FOV） | 60° |
| 左右摄像头基线距离 | 0.12m |
| 安装位置 | 车头前方0.10m，离地0.30m，光轴水平朝前，左右摄像头水平排列 |

---

## 十、车辆物理参数

| 参数 | 取值 |
|------|------|
| 车辆质量 | 1.5 kg |
| 轴距 | 0.25m |
| 最大行驶速度（无加速包） | 10 m/s |
| 最大行驶速度（加速包激活） | 13 m/s（基础值 × 1.3）|
| 最大转向角 | ±0.5 rad（约±28.6°）|
| 从0加速至最大速度所需时间 | 约1.5秒 |
| 最小转弯半径（最大转向角下） | 约1.5m |
| 仿真物理步长 | 与世界文件 `basicTimeStep` 一致，设为 64ms |

---

## 十一、数据字典

本节对文档中出现的所有枚举值、计算字段及复合类型给出一种定义方法。供参考。

---

### 11.1 `lap_progress`

**类型**：float  
**出现位置**：IPC 数据（3.2节）、WebSocket 推送（3.3节）、排名规则（1.4节）

**定义**：  
`lap_progress` 表示当前车辆在本圈内已通过的检查点数量占总检查点数量的比例，取值为 {0.00, 0.25, 0.50, 0.75} 之一。  

Supervisor 为每辆车维护当前圈内已按序通过的检查点数量 $k$（整数，范围 0~3）：

$$\text{lap\_progress} = k \div 4$$

**各区间对应值：**

| 车辆当前位置（本圈内） | `k` | `lap_progress` |
|----------------------|-----|---------------|
| 已过 CP0（本圈开始），尚未到达 CP1 | 0 | 0.00 |
| 已按序过 CP0→CP1，尚未到达 CP2 | 1 | 0.25 |
| 已按序过 CP0→CP1→CP2，尚未到达 CP3 | 2 | 0.50 |
| 已按序过 CP0→CP1→CP2→CP3，尚未到达 CP0 | 3 | 0.75 |
| 再次经过 CP0，完成一圈 | 触发 `lap_complete`，`k` 重置为 0，`lap += 1`，`lap_progress` 重置为 0.00 | — |

**说明：**  
- `lap_progress` 仅在区间边界（检查点处）跳变，两个检查点之间保持不变
- 排位赛 DNF 排名、竞速赛未完赛排名均使用 `lap_progress` 作为同圈数内的次级排名依据
- 车辆在排位赛开始前、尚未触发第一个 CP0 时，`lap_progress = 0.00`，`lap = 0`

---

### 11.2 `heading`

**类型**：float  
**出现位置**：IPC 数据（3.2节）、WebSocket 推送（3.3节）

**定义**：  
车辆在世界坐标系中的朝向角，单位弧度，范围 $[-\pi, +\pi]$。

- 角度以世界坐标系 $+X$ 轴方向为基准（= 0 rad）
- 角度增大方向为**逆时针**（从上俯视）
- 示例：朝向 $+X$ 为 0 rad；朝向 $+Y$ 为 $+\pi/2$ rad；朝向 $-X$ 为 $\pm\pi$ rad；朝向 $-Y$ 为 $-\pi/2$ rad

计圈规则（6.6节）中判断"向前行驶"的条件：车辆 `heading` 与赛道该段的切线方向之差的绝对值小于 $\pi/2$ rad。

---

### 11.3 `status` 枚举

**类型**：string  
**出现位置**：IPC 数据（3.2节）、WebSocket 推送（3.3节）

| 取值 | 含义 | 进入条件 | 退出条件 |
|------|------|----------|----------|
| `"normal"` | 车辆正常行驶，Supervisor 不对其速度进行干预 | 初始状态；从 `"stopped"` 恢复时 | 触发碰撞惩罚或判负 |
| `"stopped"` | 车辆被强制停止，Supervisor 将速度输出覆盖为 0 | 发生严重碰撞（2秒停止惩罚）；沙箱子进程崩溃等待重启（2秒） | 停止计时结束，自动恢复为 `"normal"` |
| `"disqualified"` | 本场判负，车辆不再接受控制输入，停止于原地 | 同一场累计3次严重碰撞；沙箱触发非法系统调用（`SIGSYS`）| 本场比赛结束（不可在本场中恢复）|

---

### 11.4 事件类型（`events[].type`）

IPC（3.2节）与 WebSocket（3.3节）中 `events` 数组内每项的 `type` 字段枚举如下：

#### `lap_complete`
**触发条件**：车辆按序（CP0→CP1→CP2→CP3→CP0）完整通过一圈，在第二次经过 CP0 时触发。

| 字段 | 类型 | 说明 |
|------|------|------|
| `team_id` | string | 完成本圈的队伍 |
| `lap_number` | int | 刚完成的圈序号（从1开始计数） |
| `lap_time` | float | 本圈用时（秒），从本圈起始 CP0 到本次 CP0 的仿真时间差 |

#### `collision`
**触发条件**：Webots 检测到车辆与障碍物或其他车辆发生接触（见6.7节）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `team_id` | string | 受到碰撞影响的车辆所属队伍 |
| `severity` | string | `"minor"`（轻微碰撞）/ `"major"`（严重碰撞），定义见11.5节 |
| `collision_with` | string | `"obstacle"`（与障碍物碰撞）/ `"car"`（与其他参赛车辆碰撞）|

#### `powerup_pick`
**触发条件**：车辆中心点进入加速包碰撞框，Supervisor 判定拾取成功。

| 字段 | 类型 | 说明 |
|------|------|------|
| `team_id` | string | 拾取加速包的队伍 |
| `powerup_id` | string | 被拾取加速包的唯一标识，格式：`"p_{序号}"` |
| `effect_duration` | float | 加速效果持续时间（秒），固定为 2.0 |

#### `timeout_warn`
**触发条件**：`car_controller.py` 在20ms内未收到沙箱子进程的控制输出，在使用上一帧数据继续后立即推送本事件。

| 字段 | 类型 | 说明 |
|------|------|------|
| `team_id` | string | 发生超时的队伍 |
| `warn_count` | int | 本场内累计超时次数（1~3）；达到3时同时触发本圈作废逻辑 |

#### `obstacle_spawn`
**触发条件**：Supervisor 动态生成一个橙色临时锥桶。

| 字段 | 类型 | 说明 |
|------|------|------|
| `obstacle_id` | string | 新生成障碍物的唯一标识，格式：`"dyn_{序号}"` |
| `x` | float | 生成位置的世界坐标 X（米） |
| `y` | float | 生成位置的世界坐标 Y（米） |

#### `obstacle_remove`
**触发条件**：动态障碍物被车辆碰撞后删除，或被 Supervisor 手动清场时删除。

| 字段 | 类型 | 说明 |
|------|------|------|
| `obstacle_id` | string | 被删除障碍物的唯一标识 |

#### `leader_finished`
**触发条件**：本场第一辆车完成规定圈数（触发 `lap_complete` 且 `lap_number == total_laps`），Supervisor 启动60秒宽限期计时时推送本事件。

| 字段 | 类型 | 说明 |
|------|------|------|
| `team_id` | string | 第一完赛车辆所属队伍 |
| `finish_time` | float | 领先车完赛时刻的仿真时间（秒） |
| `grace_end_time` | float | 宽限期结束时刻的仿真时间（秒），始终等于 `finish_time + 60.0` |

#### `race_end`
**触发条件**：宽限期60秒结束后，Supervisor 推送本事件并停止所有车辆。

| 字段 | 类型 | 说明 |
|------|------|------|
| `reason` | string | 固定为 `"grace_period_expired"` |
| `final_rankings` | array | 本场最终排名列表，每项包含 `rank`（int）、`team_id`（string）、`total_time`（float，未完赛为 null） |

---

### 11.5 `severity` 枚举（碰撞严重程度）

| 取值 | 判定条件 |
|------|----------|
| `"minor"` | 车辆与障碍物碰撞时相对速度 < 3 m/s；或两车之间发生侧面轻微接触。处理：被碰车辆速度降至当前速度的70%，持续1秒 |
| `"major"` | 车辆与障碍物碰撞时相对速度 ≥ 3 m/s；或两车之间发生正面碰撞。处理：被碰车辆强制停止2秒（状态置为 `"stopped"`） |

---

### 11.6 `session_type` 枚举

**出现位置**：`race_config.json`（3.4节）、WebSocket 推送（3.3节）

| 取值 | 含义 |
|------|------|
| `"qualifying"` | 排位赛（计时赛，各车独立计时，不竞争）|
| `"group_race"` | 分组赛（竞速赛制）|
| `"semi"` | 半决赛（竞速赛制）|
| `"final"` | 决赛（竞速赛制）|
| `"test"` | 单车测试任务（代码提交后的模拟测试，仅出现于测试队列上下文，不写入正式比赛数据库）|

---

### 11.7 `session_id` 格式规范

**出现位置**：`race_config.json`（3.4节）、WebSocket 推送（3.3节）

| 场次类型 | 格式 | 示例 |
|----------|------|------|
| 排位赛（第N批） | `"qualifying_{N}"` | `"qualifying_3"` |
| 分组赛（第X组） | `"group_race_{G}"` | `"group_race_G1"` |
| 半决赛（第N场） | `"semi_{N}"` | `"semi_2"` |
| 决赛 | `"final"` | `"final"` |
| 测试任务 | `"test_{team_id}_{YYYYMMDD_HHMMSS}"` | `"test_A01_20260410_153021"` |

`{G}` 对应分组赛的组别标识（G1~G7），与蛇形分组结果中的组别编号一致。

---

### 11.8 `phase` 枚举（WebSocket 推送状态）

**出现位置**：WebSocket 推送（3.3节）

| 取值 | 含义 |
|------|------|
| `"waiting"` | 本场已配置（`race_config.json` 已写入），等待助教通过 `/api/admin/start-race` 下令开始 |
| `"running"` | 比赛进行中，Supervisor 持续推送数据 |
| `"grace_period"` | 领先车辆已完赛，宽限期（60秒）倒计时中；仍有车辆在行驶 |
| `"finished"` | 本场比赛已正式结束，最终排名已写入数据库，数据保留供前端展示 |
| `"aborted"` | 比赛被助教手动终止（`POST /api/admin/stop-race`），该场成绩按终止时刻数据记录 |

---

### 11.9 测试报告 `finish_reason` 枚举

**出现位置**：代码提交与测试系统（7.1节）中的测试报告字段

| 取值 | 含义 |
|------|------|
| `"completed"` | 成功完成2圈，测试正常结束 |
| `"timeout"` | 测试运行达到上限时间（5分钟），车辆仍未完成2圈 |
| `"crashed"` | 沙箱子进程崩溃后无法重启，车辆无法继续行驶 |
| `"disqualified"` | 累计3次严重碰撞，或沙箱触发非法系统调用，本次测试判负 |


# AI Racer 平台开发任务书

> 2026年春季数算B大作业——AI赛车竞速平台  
> 版本 v1.3 | 2026-04-10  

---

## 一、项目概述

### 1.1 背景

本平台为课程大作业竞赛系统。参赛学生团队（约25组）各自编写纯视觉自动驾驶算法，算法以 Python 文件形式提交，由平台加载到 Webots 仿真车辆上，在同一台中心机器上进行实时仿真竞速比赛。

### 1.2 系统功能要求

1. **输入限制**：所有参赛车辆的控制算法唯一数据来源为双目摄像头图像（BGR格式 numpy 数组），平台不向算法提供位置坐标、速度、地图或任何其他传感器数据
2. **统一参数**：所有参赛车辆的物理参数、摄像头参数、起跑位置间距完全一致
3. **实时可视化**：仿真进行中，比赛画面和数据实时推送到前端，可通过局域网内任意浏览器访问
4. **自助模拟测试**：参赛队伍在赛前提交代码后，可在平台上申请单车模拟测试，查看算法运行结果，并可多次更新提交
5. **代码隔离执行**：每支队伍的代码运行在独立沙箱进程中，不能访问文件系统、网络或其他队伍的数据
6. **赛程管理**：助教通过管理控制台控制赛程推进，包括开始/停止比赛、锁定代码提交、调整分组对阵

### 1.3 技术栈

| 层次 | 技术 |
|------|------|
| 仿真平台 | Webots R2023b（Linux 版）|
| 仿真控制器 | Python 3.10+ |
| 后端 | Python / FastAPI / SQLite / WebSocket |
| 前端 | HTML + CSS + JavaScript（原生，不依赖前端框架）|
| 运行平台 | Linux（中心机器），局域网内浏览器访问 |

### 1.4 架构总览

```
┌──────────────────────────────────────────────────────────┐
│                     中心机器 (Linux)                      │
│                                                          │
│  ┌─────────────────────┐    ┌────────────────────────┐   │
│  │    模块一 + 模块二    │    │        模块三           │   │
│  │  Webots 仿真环境     │TCP │    赛事管理后端          │   │
│  │  + 仿真控制器        │◄──►│    FastAPI + WebSocket  │   │
│  └─────────────────────┘    └──────────┬───────────────┘  │
│  Webots Web Stream (port 1234)          │ WebSocket / REST  │
└──────────────────────┬─────────────────┼───────────────────┘
                       │                 │
                       ▼                 ▼
              ┌─────────────────────────────────────┐
              │      模块四：前端（浏览器访问）        │
              │  大屏比赛页 / 提交页 / 助教控制台     │
              └─────────────────────────────────────┘
```

---

## 二、赛事规则说明（开发参考）

### 2.1 赛制结构

参赛队伍数量约25组，每场仿真同时运行2~4辆车。赛制按以下顺序执行：

```
排位赛（全员，共7批次，每批3~4队，各自独立计时）
    │
    ├─ 按排位成绩进行蛇形分组
    ▼
分组赛（共7场，每场3~4队，同场竞速）
    │
    ├─ 各场第1名（共7队）+ 所有第2名中排位成绩最快者（1队）= 8队晋级
    ▼
半决赛（共2场，每场4队）
    │
    ├─ 每场前2名晋级，共4队进入决赛
    ▼
决赛（1场，4队）
```

**阶段说明：**

| 阶段 | 场次数 | 每场车辆数 | 固定圈数 | 预计耗时 |
|------|--------|------------|----------|----------|
| 排位赛 | 7批 | 3~4辆 | 2圈（计时） | 约35分钟 |
| 分组赛 | 7场 | 3~4辆 | 3圈 | 约35分钟 |
| 半决赛 | 2场 | 4辆/场 | 3圈 | 约12分钟 |
| 决赛 | 1场 | 4辆 | 5圈 | 约8分钟 |
| 合计 | — | — | — | 约1.5小时（含场间 Webots 重启和代码加载时间）|

### 2.2 竞速赛制与排名规则

**赛制类型（分组赛 / 半决赛 / 决赛）：竞速赛制（固定圈数）**

各阶段规定圈数：分组赛3圈、半决赛3圈、决赛5圈。

**比赛结束条件：**
1. 本场第一辆车完成规定圈数并经过终点线时，Supervisor 启动60秒宽限计时
2. 宽限期内完成规定圈数的车辆均记录完赛时间（从比赛开始到经过终点线的仿真时间）
3. 60秒宽限期结束后，比赛正式结束

**排名规则（优先级从高到低）：**
1. 宽限期内完成规定圈数的车辆：按完赛时间升序排列
2. 宽限期结束时未完成规定圈数的车辆：按已完成圈数降序排列；圈数相同时按 `lap_progress` 降序排列；所有未完赛车辆排在已完赛车辆之后

**排位赛成绩：** 计时赛，每辆车最多完成2圈。取2圈内最快单圈时间。未完成任意一圈者记为 DNF，排在已完成队伍之后，DNF 内部按 `lap_progress` 降序排列。

### 2.3 晋级规则

- 分组赛各场第1名自动晋级半决赛（共7名）
- 剩余1个半决赛席位由所有分组赛第2名中、排位赛成绩最快者获得
- 半决赛各场前2名晋级决赛（共4名）

### 2.4 学生代码接口（强制约定，所有模块开发必须遵守）

学生提交唯一文件 `team_controller.py`，该文件必须包含以下函数，签名不可修改：

```python
import numpy as np

def control(left_img: np.ndarray,
            right_img: np.ndarray,
            timestamp: float) -> tuple[float, float]:
    """
    参数：
        left_img:  左目摄像头图像，shape=(480, 640, 3)，dtype=uint8，通道顺序 BGR
        right_img: 右目摄像头图像，shape=(480, 640, 3)，dtype=uint8，通道顺序 BGR
        timestamp: 当前仿真时间，单位秒，只读，禁止基于此参数实现帧间计时逻辑

    返回值：
        steering: float，范围 [-1.0, 1.0]，负值左转，正值右转，0.0 直行
        speed:    float，范围 [0.0, 1.0]，目标速度相对于当前允许最大速度的比例

    执行时限：每次调用必须在 20ms 内返回
    """
    steering = 0.0
    speed = 0.5
    return steering, speed
```

---

## 三、模块一：Webots 仿真环境

### 3.1 负责范围

构建完整的 Webots 世界文件（`.wbt`），包含赛道几何、车辆模型、障碍物初始布置、加速包模型、光照与物理参数配置。本模块不包含控制器逻辑，控制器由模块二负责。

### 3.2 交付物

```
webots/
├── worlds/
│   └── airacer.wbt              # 主世界文件
└── protos/
    ├── RaceCar.proto            # 赛车模型（含双目摄像头节点）
    ├── TrafficCone.proto        # 锥桶（颜色通过参数配置，用于红色/橙色）
    ├── Barrier.proto            # 黄黑路障
    └── Powerup.proto            # 加速包（蓝色扁圆柱 + 旋转光环）
```

### 3.3 赛道几何规格

| 参数 | 要求 |
|------|------|
| 形状 | 闭合环形，行驶方向为顺时针 |
| 参考周长 | 150~200m |
| 主赛道宽度 | 6~8m |
| 窄道区宽度 | 4~5m |
| 最小弯道内径 | 8m |
| 地面颜色 | 深灰色，RGB 约 (60, 60, 60)，使用 asphalt 材质 |

**必须包含的路段（各路段顺序由建模人员决定，需合理连接成闭合环形）：**

| 路段 | 数量 | 具体要求 |
|------|------|----------|
| 主直道 | 1段 | 长40~50m，宽8m；起终点线设于此路段 |
| 高速弯道 | 2处 | 弯道内径15m以上 |
| 发夹弯 | 1~2处 | 弯道内径8~10m |
| S型连续弯 | 1处 | 由3~4个连续反向弯道组成，每个子弯道内径不小于10m |
| 窄道区 | 1段 | 宽4~5m，长20m |

### 3.4 车道标线规范

所有标线颜色须与地面底色 RGB(60,60,60) 形成明显对比，保证在640×480摄像头图像中可通过颜色阈值方法分割。

| 标线 | 颜色 | 宽度 | 样式 |
|------|------|------|------|
| 左侧边线 | 白色 RGB(255,255,255) | 0.10m | 连续实线 |
| 中心线 | 白色 RGB(255,255,255) | 0.08m | 虚线（1m 实 / 1m 虚）|
| 右侧边线 | 黄色 RGB(255,220,0) | 0.10m | 连续实线 |
| 路肩纹 | 红白相间 | 0.5m（总宽）| 锯齿纹，每段0.25m |
| 起终点线 | 红白横纹 | 覆盖全赛道宽度 | 连续横条 |

**光照要求：**
- 使用固定方向光，光源方向与强度在世界文件中写死，不随仿真时间变化
- 所有节点关闭 `castShadows`，禁止场景中出现动态阴影

### 3.5 车辆模型规格

| 参数 | 值 |
|------|-----|
| 质量 | 1.5 kg |
| 轴距 | 0.25m |
| 最大转向角 | ±0.5 rad |
| 最大速度（无加速包） | 10 m/s |
| 0到最大速的加速时间 | 约1.5秒 |

**双目摄像头参数：**

| 参数 | 值 |
|------|-----|
| 左右摄像头数量 | 各1个，同步输出 |
| 图像分辨率 | 640 × 480 像素 |
| 水平视场角 | 60° |
| 基线距离 | 0.12m |
| 安装位置 | 车头前方0.10m，离地0.30m，光轴水平朝前，左右摄像头水平排列 |
| 输出通道顺序 | Webots 默认输出 RGB，控制器框架（模块二）负责转换为 BGR 后传入学生代码 |

### 3.6 障碍物规格

**静态障碍（在世界文件中预置，位置固定，Supervisor 不在运行时移动）：**

| 类型 | 颜色 RGB | 几何尺寸 | 默认布置位置 |
|------|---------|---------|------------|
| 红色锥桶 | (220, 30, 30) | 高0.30m，底部直径0.20m，圆锥形 | 发夹弯入口两侧，间隔2m排列 |
| 黄黑路障 | 主体 (255,220,0)，条纹 (0,0,0) | 高0.25m，宽0.40m，长0.20m | 窄道区两侧边界，每隔3m一个 |
| 灰色石块 | (100, 100, 100) | 不规则多边形体，外接球半径0.15~0.20m | 主直道外侧路肩，每条直道不超过2个 |

所有静态障碍的底面与赛道地面贴合，不可嵌入地面或悬空。障碍物需在摄像头图像中完整可见，不可被地形或其他物体遮挡。

**动态障碍（Supervisor 在比赛运行中生成和删除，使用 TrafficCone.proto）：**

| 参数 | 规格 |
|------|------|
| 颜色 | 橙色，RGB(255, 140, 0)，与红色静态锥桶形状相同 |
| 生成规则 | 每隔30秒，从世界文件中预标注的候选坐标集合中随机选取一个位置，生成一个动态障碍节点 |
| 删除规则 | 车辆与其发生碰撞后立即删除；10秒后重新随机生成 |
| 同时存在上限 | 3个 |
| 禁止生成位置 | 弯道顶点前后各5m范围内；起终点线前后各20m范围内；当前已有车辆位置半径3m以内 |
| 候选坐标 | 由建模人员在世界文件注释中标注不少于10个候选坐标点，供 Supervisor 读取 |

**加速包（使用 Powerup.proto）：**

| 参数 | 规格 |
|------|------|
| 几何形状 | 扁平圆柱体，半径0.20m，高0.10m，底面悬浮于地面0.05m |
| 颜色 | 亮蓝色 RGB(0, 150, 255) |
| 动态效果 | 顶部附加白色半透明圆环，每仿真步旋转5°（Powerup.proto 内部实现旋转动画）|
| 候选位置 | 建模人员预设不少于6个固定候选坐标（建议位于主直道中段及高速弯出口处）|
| 激活数量 | 每场比赛开始时由 Supervisor 从候选位置中随机选取2~3个激活 |

### 3.7 隐形检查点

赛道上设置4个隐形检查区域（以坐标范围或 `TouchSensor` 实现），供 Supervisor 判断车辆是否按顺序通过。位置要求：

| 检查点 | 建议位置 |
|--------|----------|
| CP0 | 起终点线处（计圈触发点）|
| CP1 | 主直道末端，弯道入口前 |
| CP2 | 发夹弯出口 |
| CP3 | S型弯中部 |

4个检查点需均匀分布于全圈，不可集中在半圈以内。具体坐标由建模人员根据赛道实际几何确定后，以注释方式写入世界文件，供 Supervisor 读取。

### 3.8 验收标准

- [ ] Webots 可正常加载 `airacer.wbt`，物理仿真启动后无崩溃或异常
- [ ] 车辆可通过 Webots `Driver` API 接受转向角和速度指令并产生对应物理运动
- [ ] 双目摄像头节点可正常输出图像数据，可转换为 numpy ndarray
- [ ] 在640×480分辨率摄像头图像中，所有车道标线和障碍物可见、无遮挡、无极端光照导致的不可见区域
- [ ] 4个检查点坐标覆盖全圈，相邻检查点之间无法通过倒车绕过
- [ ] 所有 Proto 节点可由 Supervisor 在运行时动态创建和删除，不引发世界文件状态损坏
- [ ] 世界文件中包含不少于10个动态障碍候选坐标注释和不少于6个加速包候选坐标注释

---

## 四、模块二：仿真控制器

### 4.1 负责范围

编写两类 Webots 控制器文件：
1. **Supervisor 控制器**：拥有场景树特权访问权限，负责比赛裁判逻辑
2. **车辆控制器框架**：在 Webots 进程内运行，负责加载并调用学生代码，处理超时和崩溃

### 4.2 交付物

```
webots/controllers/
├── supervisor/
│   └── supervisor.py            # Supervisor 控制器
└── car/
    ├── car_controller.py        # 车辆控制器框架（运行于 Webots 进程内）
    └── sandbox_runner.py        # 学生代码沙箱执行器（作为独立子进程运行）
```

### 4.3 Supervisor 控制器

**职责列表：**
- 在比赛开始时读取 `race_config.json`，初始化参赛车辆列表、场次类型和规定圈数
- 维护每辆车的检查点通过序列，判断是否完成有效一圈及对应圈时
- 按竞速赛制执行比赛结束逻辑（见下方"比赛结束流程"）
- 通过 `TouchSensor` 或坐标距离检测碰撞事件，按碰撞规则执行处理
- 检测车辆是否进入加速包碰撞区域，触发加速包拾取逻辑
- 按照加速包生成规则动态创建和删除加速包节点
- 按照动态障碍生成规则随机创建和删除障碍锥桶节点
- 每仿真步（64ms）通过本地 TCP Socket 向后端推送状态数据

**比赛结束流程（竞速赛制）：**

```
初始状态：grace_period_started = False，grace_start_time = None

每仿真步检查：
    if 某辆车本步完成了第 total_laps 圈（检测到 lap_complete 且 lap == total_laps）:
        if not grace_period_started:
            grace_period_started = True
            grace_start_time = sim_time
            向后端推送事件：{"type": "leader_finished", "team_id": ..., "finish_time": sim_time}

    if grace_period_started:
        if sim_time - grace_start_time >= 60.0:
            向后端推送事件：{"type": "race_end", "sim_time": sim_time}
            停止所有车辆（Driver速度设为0），结束仿真步循环
```

排位赛（session_type = "qualifying"）不执行上述流程，每辆车完成2圈后由车辆控制器停止该车。

**推送数据格式（JSON，每64ms一条，`\n` 结尾，UTF-8编码，推送至 localhost:9100）：**

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
    {"type": "lap_complete",   "team_id": "A01", "lap_time": 43.21, "lap_number": 2},
    {"type": "collision",      "team_id": "B02", "severity": "minor", "collision_with": "obstacle"},
    {"type": "powerup_pick",   "team_id": "C03", "powerup_id": "p_04", "effect_duration": 2.0},
    {"type": "obstacle_spawn", "obstacle_id": "dyn_07", "x": 5.1, "y": 2.3},
    {"type": "timeout_warn",   "team_id": "D01", "warn_count": 2}
  ]
}
```

**碰撞判定规则：**

| 级别 | 判定条件 | 处理操作 |
|------|----------|----------|
| 轻微碰撞 | 接触时相对速度 < 3m/s | 被碰车辆速度降至当前速度的70%，持续1秒；推送 `collision(severity=minor)` |
| 严重碰撞 | 接触时相对速度 ≥ 3m/s | 被碰车辆停止运动2秒；推送 `collision(severity=major)` |
| 判负 | 同一场次同一队伍累计3次严重碰撞 | 该车标记为 `disqualified`，停止行驶至本场结束；不计入本场排名 |

**加速包拾取规则：**
- 拾取判定：车辆中心点进入加速包圆柱碰撞框
- 拾取效果：该车允许最大速度提升至基础最大速度的130%，持续2秒
- 冷却规则：同一车辆拾取后5秒内，再次进入加速包区域不触发效果
- 加速包被拾取后立即删除节点，3秒后在另一候选位置重新创建

**计圈规则：**
- Supervisor 为每辆车维护检查点通过序列，初始状态为等待 CP0
- 车辆依次经过 CP0 → CP1 → CP2 → CP3，且每段行驶时车辆 heading 方向与赛道顺时针方向夹角小于90°
- 在满足上述条件下经过 CP0 时，`lap` 计数+1，记录本圈用时，序列重置为等待 CP1
- 跳过任意检查点或逆向通过时，当前圈序列不推进，不计圈

### 4.4 车辆控制器框架（car_controller.py）

**执行流程（每仿真步64ms）：**
1. 从 Webots Camera 节点读取左右摄像头图像，转换为 BGR uint8 numpy array
2. 将图像序列化为二进制，写入对应队伍沙箱子进程的 stdin
3. 设置20ms读超时，等待子进程 stdout 返回一行 JSON：`{"steering": x, "speed": y}`
4. 解析返回值，通过 Webots `Driver` API 施加转向和速度控制

**超时处理：**

| 情况 | 处理方式 |
|------|----------|
| 单次调用超时（超过20ms未返回） | 沿用上一帧的 steering/speed 值；向 Supervisor 内部记录1次警告；`timeout_warn` 事件将在下一次 Supervisor 推送中包含 |
| 同一队伍累计3次警告 | 通知 Supervisor 执行 `lap_void`：重置该车至最近检查点，当前圈成绩取消 |
| 子进程进程退出（stdout关闭或退出码非零）| 记录崩溃日志；自动重新启动沙箱子进程；期间该车停止运动2秒 |
| 子进程触发非法系统调用（内核发送 SIGSYS）| 子进程终止后不重启；通知 Supervisor 将该车标记为 `disqualified` |

**比赛配置读取：**
控制器启动时读取 `race_config.json`（由后端在比赛开始前写入），获取本场参赛队伍列表及各队代码路径。

### 4.5 沙箱执行器（sandbox_runner.py）

作为独立子进程运行，每辆参赛车对应一个实例，在加载学生代码前施加以下资源限制：

```python
import resource, os

def apply_sandbox_limits():
    # 虚拟地址空间上限：512MB
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    # CPU 时间累计上限：10秒（防止无限循环）
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    # 禁止创建子进程
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    # 禁止写文件（最大可写文件大小为0字节）
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
```

网络命名空间隔离在父进程调用 `Popen` 时通过 `preexec_fn` 实现：

```python
proc = subprocess.Popen(
    ["python3", "sandbox_runner.py", "--team-id", team_id, "--code-path", code_path],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    preexec_fn=lambda: (os.unshare(0x40000000), apply_sandbox_limits())
    # 0x40000000 = CLONE_NEWNET，创建独立网络命名空间
)
```

**父子进程通信协议：**
- 父进程 → 子进程（stdin）：每帧发送一个二进制消息，格式为 `[4字节小端整数：左图数据长度][左图BGR bytes][4字节小端整数：右图数据长度][右图BGR bytes][8字节double：timestamp]`
- 子进程 → 父进程（stdout）：每帧返回一行 JSON 字符串，格式为 `{"steering": float, "speed": float}\n`

### 4.6 验收标准

- [ ] Supervisor 计圈判定正确：检查点必须按序通过；倒车/跳过检查点时当前圈不计入
- [ ] 碰撞三级判定规则全部可触发，处理动作与规则一致
- [ ] 加速包拾取后效果持续2秒，5秒冷却期内对同一车辆不再触发
- [ ] 动态障碍每30秒生成一次，同时存在数量不超过3个，生成位置不违反禁止区域规则
- [ ] Supervisor 每64ms向后端推送一条状态JSON，实测消息延迟（从步长触发到socket写入完成）< 5ms
- [ ] 车辆控制器单次调用超时（20ms）行为正确：沿用上帧值，记录警告
- [ ] 累计3次警告后触发 `lap_void`，车辆正确重置
- [ ] 沙箱子进程无法访问网络（可用 `nc` 测试连接局域网地址）
- [ ] 沙箱子进程无法写入文件（`RLIMIT_FSIZE=0` 验证）
- [ ] 子进程崩溃后车辆控制器自动重启，不影响同场其他车辆的正常运行

---

## 五、模块三：赛事管理后端

### 5.1 负责范围

后端服务的全部功能：接收 Supervisor 数据、维护比赛状态机、计算实时排名、向前端广播数据、提供代码提交的 HTTP API 和测试队列管理。

### 5.2 交付物

```
server/
├── main.py                      # FastAPI 应用入口，挂载所有路由
├── race/
│   ├── state_machine.py         # 比赛状态机
│   ├── session.py               # Webots 进程启动/停止管理
│   ├── scoring.py               # 实时排名计算
│   └── ipc.py                   # TCP Socket 接收 Supervisor 推送数据
├── api/
│   ├── submission.py            # 代码提交与即时检查 API
│   ├── testqueue.py             # 测试队列管理 API
│   └── admin.py                 # 助教控制 API（需密码验证）
├── ws/
│   └── broadcaster.py           # WebSocket 广播管理
└── db/
    └── models.py                # SQLite 数据模型
```

### 5.3 REST API 接口定义

**代码提交接口（学生使用，队伍ID + 密码鉴权）：**

```
POST /api/submit
Content-Type: application/json
Body:
{
  "team_id": "A01",
  "password": "xxxx",
  "code": "<文件内容的 base64 编码字符串>"
}

Response 200（通过检查，已入队）：
{
  "status": "queued",
  "version": "20260410_153021",
  "queue_position": 3
}

Response 400（检查失败）：
{
  "status": "error",
  "stage": "syntax_check",
  "detail": "SyntaxError at line 14: invalid syntax"
}

Response 403（提交已锁定）：
{
  "status": "locked",
  "detail": "Submission is closed. Race is about to begin."
}
```

**测试状态查询（学生使用）：**

```
GET /api/test-status/{team_id}
Headers: Authorization: Basic base64(team_id:password)

Response 200：
{
  "team_id": "A01",
  "latest_version": "20260410_153021",
  "queue_status": "waiting",      // waiting | running | done | no_submission
  "queue_position": 2,            // 当前在队列中的位置，running时为0
  "report": {                     // 仅 done 状态时有此字段
    "laps_completed": 2,
    "best_lap_time": 43.21,
    "collisions_minor": 1,
    "collisions_major": 0,
    "timeout_warnings": 0,
    "finish_reason": "completed"  // completed | timeout | crashed | disqualified
  }
}
```

**助教控制接口（需密码验证）：**

```
POST /api/admin/lock-submissions
  → 锁定所有队伍的代码提交入口，操作不可逆

POST /api/admin/set-session
Body: {"session_type": "qualifying|group_race|semi|final", "session_id": "G1", "team_ids": [...], "total_laps": 3}
  → 配置下一场比赛的参数，写入 race_config.json

POST /api/admin/start-race
  → 启动 Webots 进程，开始当前场比赛

POST /api/admin/stop-race
  → 强制终止 Webots 进程，将当前场标记为 aborted

POST /api/admin/reset-track
  → 终止当前 Webots 进程（如有），清空 race_config.json，状态机回退至 IDLE

GET  /api/admin/standings
  → 返回所有队伍的当前场次积分和排位赛成绩

GET  /api/admin/schedule
  → 返回当前赛程安排（分组赛对阵表）

POST /api/admin/override-schedule
Body: {"group_id": "G1", "team_ids": ["A01", "C03", "B05", "D02"]}
  → 助教手动修改某场分组赛的参赛队伍
```

**公开数据接口（无需鉴权）：**

```
GET /api/teams
  → 返回队伍列表（team_id, team_name），不含密码等敏感信息

GET /api/results
  → 返回所有已完成场次的结果

GET /api/schedule
  → 返回赛程安排
```

### 5.4 WebSocket 接口

**监听地址：** `ws://0.0.0.0:8000/ws/race`

**推送触发机制：**
- 常规推送：独立定时器，约30Hz
- 即时推送：收到以下事件时立即推送，不等待下一个30Hz周期：`lap_complete`、`collision`、`powerup_pick`、`race_start`、`race_end`

**推送数据格式：**

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

**`phase` 字段取值范围：**

| 取值 | 含义 |
|------|------|
| `"waiting"` | 本场已配置，等待助教执行开始指令 |
| `"running"` | 比赛进行中 |
| `"finished"` | 比赛正常结束 |
| `"aborted"` | 比赛被助教手动终止 |

**客户端连接后的初始化：**
客户端连接 WebSocket 后，服务端立即推送一条包含当前完整状态的消息（与常规推送格式相同），用于前端初始化显示。

### 5.5 比赛状态机

状态机维护全局赛事状态，所有转换须由助教通过管理 API 主动触发，**禁止自动跳转**（唯一例外：Webots 进程自然结束时，状态从 `*_RUNNING` 自动转为 `*_FINISHED`）。

```
IDLE
  │ POST /api/admin/set-session + start-race
  ▼
QUALIFYING_RUNNING   ── Webots 运行中，接收 Supervisor 数据
  │ Webots 进程退出 或 stop-race
  ▼
QUALIFYING_FINISHED  ── 本批成绩写入数据库
  │ 所有批次完成后：POST /api/admin/finalize-qualifying
  ▼
QUALIFYING_DONE      ── 排位成绩排序完毕，分组赛对阵计算完毕
  │ set-session(group_race) + start-race（共循环7次）
  ▼
GROUP_RACE_RUNNING → GROUP_RACE_FINISHED（每场结束后写入场次结果）
  │ 7场全部完成后：POST /api/admin/finalize-group
  ▼
GROUP_DONE           ── 8强名单确定
  │ set-session(semi) + start-race（共循环2次）
  ▼
SEMI_RUNNING → SEMI_FINISHED
  │ 2场全部完成后：POST /api/admin/finalize-semi
  ▼
SEMI_DONE            ── 4强名单确定
  │ set-session(final) + start-race
  ▼
FINAL_RUNNING → FINAL_FINISHED
  │ POST /api/admin/close-event
  ▼
CLOSED               ── 所有结果已持久化，前端展示最终排名
```

**状态机约束：**
- 非合法顺序的状态跳转请求（如从 `QUALIFYING_RUNNING` 直接跳至 `FINAL_RUNNING`）返回 HTTP 400
- 所有 `*_RUNNING` 状态下，测试队列暂停消费，比赛结束后自动恢复

### 5.6 测试队列

- 代码通过提交检查后自动加入 FIFO 队列尾部
- 队列为单线程串行消费，同一时刻最多运行一个测试 Webots 实例
- 若同一队伍在队列中已存在一条**尚未开始执行**的任务，新提交入队时替换旧任务
- 若旧任务已开始执行，则不中断，新提交作为新条目追加到队列尾部
- 所有 `*_RUNNING` 状态下暂停消费，`*_FINISHED` 或 `IDLE` 状态下自动恢复
- 每次测试：启动单车 Webots 实例 → 运行至完成2圈或超过5分钟 → 关闭 Webots → 写入测试报告
- 测试报告字段：`laps_completed`, `best_lap_time`, `collisions_minor`, `collisions_major`, `timeout_warnings`, `finish_reason`
- 测试报告仅该队伍通过鉴权访问，其他队伍无法查询

### 5.7 数据库表结构

```sql
-- 队伍信息
teams (
    id          TEXT PRIMARY KEY,  -- 队伍ID，如 "A01"
    name        TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at  TEXT NOT NULL
)

-- 代码提交版本
submissions (
    id          TEXT PRIMARY KEY,  -- 时间戳字符串，如 "20260410_153021"
    team_id     TEXT NOT NULL,
    code_path   TEXT NOT NULL,     -- 文件系统存储路径
    submitted_at TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1  -- 0: 被后续版本替代; 1: 当前有效版本
)

-- 测试记录
test_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id   TEXT NOT NULL,
    status          TEXT NOT NULL,    -- queued | running | done | skipped
    queued_at       TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    laps_completed  INTEGER,
    best_lap_time   REAL,
    collisions_minor INTEGER,
    collisions_major INTEGER,
    timeout_warnings INTEGER,
    finish_reason   TEXT              -- completed | timeout | crashed | disqualified
)

-- 比赛场次记录
race_sessions (
    id          TEXT PRIMARY KEY,     -- 如 "qualifying_batch_3"、"group_race_G2"
    type        TEXT NOT NULL,        -- qualifying | group_race | semi | final
    team_ids    TEXT NOT NULL,        -- JSON 数组字符串
    total_laps  INTEGER NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    phase       TEXT NOT NULL,        -- waiting | running | finished | aborted
    result      TEXT                  -- JSON 对象，比赛结束后写入
)

-- 分组赛场内积分（用于确定晋级名单）
race_points (
    team_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    rank        INTEGER,
    points      INTEGER,
    PRIMARY KEY (team_id, session_id)
)
```

### 5.8 验收标准

- [ ] 所有 REST API 端点返回正确的 HTTP 状态码和响应体，包含必要的错误信息
- [ ] WebSocket 客户端连接后立即收到完整当前状态；断线后可重新连接并恢复正常接收
- [ ] 状态机拒绝非法顺序跳转，返回 HTTP 400 并描述当前状态
- [ ] 实时排名在每次收到 `lap_complete` 事件后更新，更新结果在下一次 WebSocket 推送中体现
- [ ] 测试队列在比赛期间暂停，比赛结束后自动恢复消费，队列顺序严格遵循 FIFO（含替换规则）
- [ ] 代码锁定后提交接口返回 HTTP 403
- [ ] Webots 进程意外退出（非助教主动停止）时，后端检测到退出码，将当前场次标记为 `aborted`，并通过 WebSocket 推送状态变更
- [ ] 数据库在后端重启后仍保留所有历史比赛结果（使用 SQLite 持久化，非内存数据库）

---

## 六、模块四：前端可视化

### 6.1 负责范围

三个独立页面，使用原生 HTML + CSS + JavaScript 实现，不依赖任何前端框架。所有动态数据通过 WebSocket 或 HTTP 轮询从后端获取。

### 6.2 交付物

```
frontend/
├── race/
│   ├── index.html               # 大屏比赛页（目标显示设备：1920×1080 投影仪）
│   ├── minimap.js               # 2D 小地图渲染模块（Canvas）
│   └── leaderboard.js           # 排行榜与事件提示模块
├── submit/
│   └── index.html               # 学生代码提交页
└── admin/
    └── index.html               # 助教控制台
```

### 6.3 大屏比赛页（/race/index.html）

该页面用于在比赛现场投屏，须在 1920×1080 分辨率下各区块均可见、无内容溢出或遮挡。

**布局结构（参考，实现时可调整比例）：**

```
┌───────────────────────────────────────────────────────────┐
│  场次名称: 分组赛 第3场      仿真时间: 02:34.51    [LIVE]  │  ← 顶部信息栏
├──────────────────────────────┬────────────────────────────┤
│                              │  排名  队伍名   圈数  用时  │
│    Webots 3D 串流             │   1    队伍A     2   88.4s │
│    (iframe, port 1234)       │   2    队伍C     2   89.1s │
│                              │   3    队伍B     1   45.2s │
│                              │   4    队伍D     1   46.8s │
├──────────────────────────────┼────────────────────────────┤
│  2D 小地图（Canvas）           │  车辆状态列表               │
│  赛道轮廓 + 实时车辆位置       │  A01  8.3m/s  圈2  正常    │
│  + 障碍物 + 加速包位置         │  C03  7.9m/s  圈2  正常    │
│                              │  B05  6.1m/s  圈1  已判负  │
├──────────────────────────────┴────────────────────────────┤
│  事件记录（滚动显示最近事件）                               │
│  [02:34] 队伍C 拾取加速包    [02:31] 队伍B 严重碰撞 (2/3)  │
└───────────────────────────────────────────────────────────┘
```

**2D 小地图实现要求：**
- 赛道轮廓为预绘制的固定背景（SVG 或 Canvas 静态层），根据 Webots 世界文件的赛道几何绘制
- 车辆位置来自 WebSocket 推送的 `(x, y, heading)` 字段，每次收到数据时更新
- 每辆车以不同颜色实心圆点表示，附带指向 heading 方向的箭头指示行驶方向
- 显示当前所有动态障碍物和加速包的位置（来自 WebSocket events 数据）
- 小地图数据更新间隔由 WebSocket 推送频率决定（约30Hz）

**排行榜更新规则：**
- 每次收到 WebSocket 推送时更新排行榜显示
- 排名变化时，对应行需有明显的位置变化动效（CSS transition 即可，非必须）

**事件提示行为：**

| 事件类型 | 提示内容 | 显示时长 |
|----------|----------|----------|
| `collision(minor)` | "[队伍名] 轻微碰撞" | 显示2秒 |
| `collision(major)` | "[队伍名] 严重碰撞 (N/3)" | 显示3秒 |
| `collision(disqualified)` | "[队伍名] 累计3次严重碰撞，本场判负" | 显示5秒 |
| `powerup_pick` | "[队伍名] 拾取加速包，速度+30%，持续2秒" | 显示2秒 |
| `lap_complete` | "[队伍名] 完成第N圈，圈速 X.XXs" | 显示3秒 |
| `race_end` | "本场比赛结束，最终排名: [队伍名1], [队伍名2]..." | 显示10秒 |

多个事件同时触发时，采用队列方式顺序显示，不同时堆叠。

**技术要求：**
- Webots 3D 串流嵌入方式：`<iframe src="http://localhost:1234">`
- 所有动态数据通过 WebSocket `ws://localhost:8000/ws/race` 获取，不使用 HTTP 轮询
- WebSocket 连接断开时，页面在3秒内自动重连（指数退避，最大重试间隔15秒）
- 重连期间页面不清空当前数据，显示"连接中断，正在重连..."提示

### 6.4 代码提交页（/submit/index.html）

**功能列表：**
1. 队伍 ID + 密码登录（局部状态，不需要 session/cookie，页面刷新后重新输入）
2. 代码文件上传：支持文件拖拽和点击选择，限制文件类型为 `.py`，文件大小限制 1MB
3. 提交后即时展示后端返回的检查结果：
   - 通过：显示版本号、当前队列位置
   - 失败：显示失败阶段（语法检查/接口检查）和具体错误信息（包含行号）
4. 轮询 `/api/test-status/{team_id}`（每5秒一次），展示当前测试状态：
   - 等待中：显示队列位置和预计等待条目数
   - 运行中：显示"测试进行中"，提供跳转链接到测试观看页（`http://localhost:1234` 的 Webots 串流页）
   - 已完成：展示测试报告（完成圈数、最快圈时、碰撞次数、超时警告次数、结束原因）
5. 历史提交记录列表：展示本队所有历史版本的提交时间、版本号和对应的测试结果摘要
6. 代码提交入口锁定后：文件上传控件和提交按钮变为不可交互状态，并显示说明文字

**数据访问范围约束：**
- 提交页不展示其他队伍的任何信息（代码、测试结果、队伍名称等）
- 鉴权失败时，所有接口返回 HTTP 401，页面仅显示登录表单

### 6.5 助教控制台（/admin/index.html）

通过页面内密码输入框鉴权，密码正确后显示控制台内容，密码通过 HTTP Basic Auth 方式传递给后端 `/api/admin/*` 接口。

**功能列表：**
1. 所有队伍代码提交状态总览：队伍ID、队伍名、最新提交时间、是否已有通过检查的版本
2. **锁定提交**按钮：点击时显示二次确认对话框，确认后调用 `/api/admin/lock-submissions`；锁定后按钮变灰并显示"已锁定"
3. 比赛场次配置：
   - 下拉选择场次类型（排位赛批次N / 分组赛场次X / 半决赛N / 决赛）
   - 根据蛇形分组算法自动填充参赛队伍列表，可手动修改
   - 设置本场总圈数
   - 确认后调用 `set-session`，页面显示当前配置内容
4. **开始比赛** / **停止比赛** / **重置赛道** 按钮，每个操作前显示二次确认对话框
5. 实时积分总表：展示所有队伍的排位赛成绩、各场分组赛积分、当前总积分，按总积分降序排列
6. 测试队列视图：显示当前队列中的所有条目（队伍ID、提交版本、排队时间）及正在执行的测试；支持手动移除某条队列条目

### 6.6 验收标准

- [ ] 大屏比赛页在 1920×1080 分辨率的 Chrome 浏览器中，所有区块内容可见且不重叠、不溢出
- [ ] Webots 3D 串流 iframe 正常加载并显示仿真画面
- [ ] 小地图车辆位置从 WebSocket 收到数据到渲染完成的延迟 < 50ms
- [ ] WebSocket 断线后在3秒内开始重连，重连成功后数据恢复正常推送
- [ ] 多个事件同时到达时，事件提示按队列顺序显示，不同时重叠
- [ ] 代码提交页：上传 `.py` 文件后，在2秒内展示后端返回的检查结果
- [ ] 代码提交页：测试报告数据正确展示（与后端 `/api/test-status` 返回一致）
- [ ] 代码提交页：锁定后提交控件不可用，历史记录仍可查看
- [ ] 助教控制台：所有操作均有二次确认步骤，且操作完成后有明确的成功/失败反馈
- [ ] 三个页面在 Chrome、Firefox、Edge 最新稳定版本均可正常使用

---

## 七、模块间接口约定

各模块独立开发时必须遵守以下接口规范，以保证集成时不需要修改对接代码。

### 接口①：Supervisor → 后端（TCP Socket）

- 连接方式：Supervisor 作为 TCP 客户端，连接 `127.0.0.1:9100`（后端监听）
- 数据格式：每条消息为 UTF-8 编码的 JSON 字符串，以 `\n` 结尾
- 推送频率：每仿真步一条（步长64ms，约15条/秒）
- 字段定义：见第四章"推送数据格式"

### 接口②：后端 → 前端（WebSocket）

- 监听地址：`ws://0.0.0.0:8000/ws/race`
- 数据格式：JSON 文本帧
- 推送频率：约30Hz 常规推送 + 即时事件推送
- 字段定义：见第五章"WebSocket 接口"

### 接口③：后端启动 Webots（subprocess）

后端通过 `subprocess.Popen` 启动 Webots 进程，命令行格式：

```bash
# 正式比赛（含3D串流，供前端嵌入）
webots --stream="port=1234" /path/to/airacer.wbt

# 单车测试（不需要对外串流时，可关闭渲染以节省资源）
webots --minimize --no-rendering /path/to/airacer.wbt
```

Linux headless 环境下需配合虚拟显示运行：
```bash
Xvfb :99 -screen 0 1280x720x24 &
DISPLAY=:99 webots --stream="port=1234" /path/to/airacer.wbt
```

后端须监控 Webots 子进程状态，进程退出时记录退出码并触发状态机转换。

### 接口④：后端 → 控制器（比赛配置文件）

每场比赛开始（`start-race`）前，后端写入以下配置文件，Supervisor 和车辆控制器在启动时读取：

```json
{
  "session_id": "group_race_G3",
  "session_type": "group_race",
  "total_laps": 3,
  "ipc_port": 9100,
  "cars": [
    {
      "car_node_id": "car_1",
      "team_id": "A01",
      "team_name": "队伍A",
      "code_path": "/submissions/A01/20260410_153021/team_controller.py",
      "start_position": 1
    },
    {
      "car_node_id": "car_2",
      "team_id": "C03",
      "team_name": "队伍C",
      "code_path": "/submissions/C03/20260410_162845/team_controller.py",
      "start_position": 2
    }
  ]
}
```

配置文件路径固定为 `/path/to/airacer/race_config.json`，控制器使用相对路径或环境变量定位。

---

## 八、开发优先级与注意事项

### 8.1 开发优先级

**P0（平台基本可运行所必须完成的功能）：**

- 赛道建模 + 车辆模型（模块一）
- Supervisor 计圈逻辑 + IPC 推送（模块二）
- 车辆控制器框架 + 沙箱子进程（模块二）
- 后端 IPC 接收 + WebSocket 广播（模块三）
- 后端状态机基础流转（非全部状态，能运行单场即可）（模块三）
- 大屏比赛页（Webots 串流 + 小地图 + 排行榜）（模块四）

**P1（比赛完整流程所需功能）：**
- 动态障碍 + 加速包生成逻辑（模块二）
- 后端完整状态机（所有阶段）（模块三）
- 代码提交 API + 即时检查（模块三）
- 测试队列系统（模块三）
- 学生代码提交页（模块四）
- 助教控制台（模块四）

**P2（可选功能，在 P1 完成后有余力时实现）：**
- 测试过程录像保存与回放
- 比赛全程数据导出（JSON 格式）
- 助教控制台中的积分历史图表展示

### 8.2 端到端联调建议

建议各模块完成 P0 后，尽早进行一次端到端联调：
1. 模块一：Webots 世界文件可正常加载，车辆可移动
2. 模块二：使用官方模板代码作为测试输入，Supervisor 开始推送 IPC 数据
3. 模块三：后端接收 IPC 数据并通过 WebSocket 广播
4. 模块四：大屏页连接 WebSocket 并正常更新小地图和排行榜

联调目标：确认四个模块的接口对接无误，数据格式一致，延迟在可接受范围内。

### 8.3 已知注意事项

- Webots 的 Camera 节点默认输出 RGB 通道顺序，车辆控制器框架在传入学生代码前须转换为 BGR（`image = image[:, :, ::-1]` 或 `cv2.cvtColor`）
- Webots 仿真时间与墙钟时间不严格一致，`sim_time` 字段可能快于或慢于真实时间，前端显示时间时须使用 `sim_time` 而非 JavaScript 的 `Date.now()`
- WebSocket 端点与前端 iframe 嵌入 Webots 串流存在跨域场景，后端须在 FastAPI 中正确配置 CORS（允许局域网内任意来源）
- 沙箱子进程中需预装 `numpy` 和 `opencv-python`，联调前须确认运行环境中已安装
- Linux headless 模式下 Webots 依赖虚拟显示（Xvfb），需提前安装并在启动脚本中配置 `DISPLAY` 环境变量

---

## 附录A：学生官方模板代码

```python
# team_controller.py
# 只需提交本文件，不要修改 control() 的函数签名

import numpy as np

def control(left_img: np.ndarray,
            right_img: np.ndarray,
            timestamp: float) -> tuple[float, float]:
    """
    参数：
        left_img:  左目图像，shape=(480, 640, 3)，dtype=uint8，BGR 通道顺序
        right_img: 右目图像，shape=(480, 640, 3)，dtype=uint8，BGR 通道顺序
        timestamp: 仿真时间（秒），只读

    返回值：
        steering: float，范围 [-1.0, 1.0]，负值左转，正值右转
        speed:    float，范围 [0.0, 1.0]，0.0 停止，1.0 最大速度

    每次调用时限：20ms
    """

    # 在此实现视觉控制算法

    steering = 0.0
    speed = 0.5

    return steering, speed
```

**运行环境预装库（可直接 import）：**
`numpy`, `cv2`（OpenCV）, `math`, `collections`, `heapq`, `functools`, `itertools`

**禁止 import 的模块：**
`os`, `sys`, `socket`, `subprocess`, `threading`, `multiprocessing`, `time`, `datetime`，及所有网络请求相关库

---

## 附录B：参考文档

- 完整架构设计文档：`docs/airacer-architecture.md`（第十一节为数据字典，定义所有枚举值和计算字段）
- Webots 官方参考手册：https://cyberbotics.com/doc/reference/index
- Webots Python API 文档：https://cyberbotics.com/doc/reference/python-api
- Webots Web Streaming 文档：https://cyberbotics.com/doc/guide/web-simulation

---


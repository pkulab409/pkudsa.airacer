## AI Racer

### 一、项目概述

《AI Racer》是基于 Webots 物理仿真的 AI 赛车竞技平台，供学生提交自动驾驶代码（纯视觉输入），在 Webots 仿真环境中进行多车实时比赛，并通过平台自动执行仿真、记录遥测、计算排名、提供赛事回放。

本项目的架构设计以去年大作业 **Tuvalon（图灵阿瓦隆）** 为蓝本，直接复用其核心设计模式，并针对 Webots 物理仿真这一新增需求做对应扩展。

> 最大的架构差异：Avalon 的游戏逻辑在 Flask 后端进程内直接运行，而 AiRacer 需要 Webots（仅支持 Linux），因此 Avalon 的 `game/` 目录被独立为网络服务 **Sim Node**，部署在 Linux 仿真服务器上。

### 二、技术文档

#### 1. Sim Node（仿真节点）核心

- **`simnode/race_manager.py`**：单例管理器，维护比赛队列和 Webots 实例
- **`simnode/race_runner.py`**：比赛执行器，驱动完整仿真流程
- **`simnode/telemetry_observer.py`**：遥测观察者，记录快照并推流
- **`simnode/car_sandbox.py`**：代码沙箱，限制学生代码执行环境

详见 `READMEs/README_simnode.md`，接口规范见 `READMEs/README_simnode_interface.md`。

#### 2. Backend 平台层

项目采用 **FastAPI** 构建 Backend。

- **应用入口 (`server/app.py`)**：FastAPI 应用初始化，配置加载，Router 注册，数据库初始化
- **蓝图 (`server/blueprints/` 目录)**：
  - `submission.py`：AI 代码管理（提交、检查、测试队列）
  - `admin.py`：助教控制台（赛事推进、仿真启停）
  - `recording.py`：录像浏览与回放数据
- **数据库 (`server/database/` 目录)**：
  - `models.py`：SQLite Schema（`teams`, `submissions`, `test_runs`, `race_sessions`, `race_points`）
  - `action.py`：CRUD 操作封装
- **服务层 (`server/services/` 目录)**：
  - `race_service.py`：比赛结束后数据库写入（对应 `battle_service.py`）
- **工具类 (`server/utils/` 目录)**：
  - `simnode_client.py`：Sim Node HTTP 客户端（将 BattleManager 方法调用转为网络调用）
- **配置 (`server/config/` 目录)**：
  - `config.py`：从 `config.yaml` 加载配置
  - `config.yaml`：数据库路径、Sim Node URL、管理员密码等

详见 `READMEs/README_blueprints.md` 和 `READMEs/README_database.md`。

#### 3. AI SDK（学生接口）

- **`sdk/team_controller.py`**：官方模板（对应 `basic_player.py`）
- **`sdk/validate_controller.py`**：本地合规验证工具

学生接口文档见 `READMEs/README_code_submission_guide.md`。

#### 4. 遥测数据格式

- 快照格式 (`TelemetryObserver.make_snapshot()` 调用规范) 见 `READMEs/README_telemetry.md`

### 三、项目架构

#### 1. 四模块设计

系统由 4 个模块构成，分别对应 4 名开发者：

| 模块 | 负责人 |
|----------------------|--------|
| **A: Frontend**| — |
| **B: Backend** | — |
| **C: Sim Node**| — |
| **D: AI SDK**   | — |

#### 2. 目录结构

```
pkudsa.airacer/
├── README.md
├── READMEs/                   # 技术文档
│   ├── README_simnode.md
│   ├── README_simnode_interface.md
│   ├── README_telemetry.md
│   ├── README_database.md
│   ├── README_blueprints.md
│   ├── README_code_submission_guide.md
│   ├── README_race_rules.md
│   ├── README_platform_operating_guide.md
│   └── README_command.md
├── frontend/                  # 模块 A：前端
│   ├── admin/
│   ├── race/
│   └── submit/
├── server/                    # 模块 B：后端
│   ├── app.py                 # 应用入口
│   ├── config/                # 配置
│   ├── blueprints/            # API 路由
│   ├── database/              # 数据库
│   ├── race/                  # 赛事状态机、积分、会话
│   ├── ws/                    # WebSocket
│   ├── services/              # 业务逻辑服务
│   └── utils/                 # 工具类
├── simnode/                   # 模块 C：仿真节点（部署在 Linux 服务器）
│   ├── server.py              # HTTP/WS 接口层
│   ├── race_manager.py        
│   ├── race_runner.py         
│   ├── telemetry_observer.py  
│   ├── car_sandbox.py         
│   ├── config/
│   └── webots/                # Webots 世界文件和控制器
│       ├── worlds/
│       └── controllers/
│           ├── supervisor/
│           └── car/
├── sdk/                       # 模块 D：AI SDK（可独立分发给学生）
│   ├── team_controller.py     # 官方模板
│   └── validate_controller.py # 本地验证工具
├── recordings/                # 录像存储（Backend 写入）
└── submissions/               # 代码存储（Backend 写入）
```

#### 3. 技术栈

- **Backend**：Python 3.10+, FastAPI, uvicorn, httpx, sqlite3
- **Sim Node**：Python 3.10+（Linux）, FastAPI, Webots
- **Frontend**：HTML, JavaScript（无框架依赖）
- **仿真**：Webots（Linux，`/usr/bin/webots`）
- **配置**：YAML

#### 4. 关键组件交互

1. **学生提交代码** → Backend `/api/submit`：即时检查（py_compile + 接口校验），通过后入测试队列
2. **测试队列消费**：Backend worker 调用 Sim Node `POST /race/create`（单车），等待 `race_ended` WebSocket 消息，写入测试报告
3. **助教启动比赛**：助教调用 Backend `POST /api/admin/start-race` → Backend 调用 Sim Node `POST /race/create` → Sim Node 启动 Webots
4. **仿真数据推流**：Webots Supervisor 每帧调用 `TelemetryObserver.make_snapshot()` → Sim Node 通过 WebSocket 推送至 Backend → Backend 持久化 + 广播至 Admin WebSocket
5. **比赛结束**：Sim Node 发送 `race_ended` 消息 → Backend 写入数据库 → 状态机推进 → 前端录像可回放

### 四、赛事规则

见 `READMEs/README_race_rules.md`。

### 五、平台操作

见 `READMEs/README_platform_operating_guide.md`。

### 六、快速开始

见 `READMEs/README_command.md`。

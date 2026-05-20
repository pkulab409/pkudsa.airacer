# Backend 蓝图文档

## 架构概述

Backend 采用 FastAPI，路由以 **APIRouter** 组织，在 `server/app.py` 中统一注册。

```
server/
├── app.py               # 生命周期 + 注册所有 router
├── blueprints/
│   ├── admin.py         # 管理员接口（赛区 CRUD、比赛控制、提交锁定）
│   ├── races.py         # 统一赛事（测试赛创建与查询）
│   ├── recording.py     # 录像浏览与遥测流
│   ├── submission.py    # 学生代码提交、激活、测试申请
│   └── team.py          # 公共查询、队伍注册
├── ws/
│   └── admin.py         # Admin WebSocket 实时推流
└── services/
    ├── race_service.py  # 比赛结束后的数据库写入
    └── test_worker.py   # 测试队列消费者
```

---

## `blueprints/submission.py`

**职责**：接收学生提交、执行代码合规检查、维护测试队列。

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| `POST` | `/api/submit` | Basic Auth | 提交代码（base64 .py，指定 slot_name） |
| `POST` | `/api/activate` | Basic Auth | 切换 race-active 槽位 |
| `POST` | `/api/test-request` | Basic Auth | 为指定槽位申请单车测试 |
| `GET`  | `/api/test-status/{team_id}` | Basic Auth | 查询三槽位状态及最新测试报告 |

**三槽位机制**：每队拥有 `main`（主力）、`dev`（开发）、`backup`（备用）。上传新版本后，该槽位旧版本自动失效（`is_active=0`）。需手动调用 `/api/activate` 切换参赛槽位，或手动申请测试。

**代码校验流程**：
1. 密码验证
2. Base64 解码并去除 BOM
3. `sdk/validate_controller.py` AST 静态扫描（禁止导入、函数签名检查、规则匹配）
4. 通过后写入文件系统 `submissions/{team_id}/{slot_name}/{timestamp}/`
5. 写入数据库 `submissions` 表

**赛区提交锁定**：Backend 检查该队所属赛区的状态机。仅 `REGISTRATION` 状态允许上传；否则返回 HTTP 403。

**测试队列**：
- 内存 FIFO 队列（`_test_queue`），由 `services/test_worker.py` 后台协程消费
- 赛程进行中（`all_running_zones()` 非空）时拒绝新的测试申请（HTTP 409）
- 同一槽位已有排队/运行中的测试时拒绝重复申请

---

## `blueprints/admin.py`

**职责**：赛区级赛事管理与控制台。

所有路由需 HTTP Basic Auth（`admin:{ADMIN_PASSWORD}`）。

### 赛区 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET`  | `/api/admin/zones` | 列出所有赛区（含状态机状态、队伍数） |
| `POST` | `/api/admin/zones` | 创建赛区（id, name, description, total_laps） |
| `DELETE` | `/api/admin/zones/{zone_id}` | 删除赛区及其所有队伍、提交、比赛记录 |
| `GET`  | `/api/admin/zones/{zone_id}/teams` | 赛区队伍列表 |
| `GET`  | `/api/admin/zones/{zone_id}/standings` | 赛区积分榜 |
| `GET`  | `/api/admin/zones/{zone_id}/bracket` | 自动赛制计算结果 |

### 比赛控制（按赛区）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/admin/zones/{zone_id}/set-session` | 配置场次（session_type, session_id, team_ids, total_laps, name） |
| `POST` | `/api/admin/zones/{zone_id}/start-race` | 启动仿真：从 waiting 队列取场次 -> 调 SimNode -> 标记 running |
| `POST` | `/api/admin/zones/{zone_id}/stop-race` | 取消当前比赛（优雅停止 + 标记 aborted/recording_ready） |
| `POST` | `/api/admin/zones/{zone_id}/reset` | 重置赛区状态机为 IDLE |
| `POST` | `/api/admin/zones/{zone_id}/finalize` | 推进赛程：结算当前阶段 -> 自动计算下一阶段对阵 -> 预创建所有 waiting 场次 -> 回到 IDLE |

### 查询辅助

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET`  | `/api/admin/zones/{zone_id}/pending-session` | 当前待开始的 waiting 场次 |
| `GET`  | `/api/admin/zones/{zone_id}/stage-sessions` | 该赛区所有场次队列（含 phase、类型、队伍数） |
| `GET`  | `/api/admin/live-frame/{session_id}` | 代理 SimNode 俯视摄像头 JPEG |

### 提交锁定（按赛区 / 全局）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/admin/zones/{zone_id}/lock-submissions` | 将指定赛区从 REGISTRATION -> IDLE（关闭提交） |
| `POST` | `/api/admin/zones/{zone_id}/unlock-submissions` | 将指定赛区从 IDLE -> REGISTRATION（开放提交） |
| `POST` | `/api/admin/lock-submissions` | 批量锁定所有 REGISTRATION 赛区 |
| `POST` | `/api/admin/unlock-submissions` | 批量解锁所有 IDLE 赛区 |

### 向后兼容的默认赛区端点

以下端点固定操作 `zone_id="default"`，保留用于旧版兼容：

`POST /api/admin/set-session`, `POST /api/admin/start-race`, `POST /api/admin/stop-race`, `POST /api/admin/reset-track`, `GET /api/admin/standings`, `POST /api/admin/finalize-placement`, `POST /api/admin/finalize-group-stage`, `POST /api/admin/finalize-semi`, `POST /api/admin/close-event`

---

## `blueprints/races.py`

**职责**：用户自主发起的测试赛事（多队对抗）。

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| `POST` | `/api/races` | Basic Auth | 创建测试赛（自选对手 2~4 队，1~10 圈，指定 world） |
| `GET`  | `/api/races/{race_id}` | 公开 | 查询单场比赛状态/结果 |
| `GET`  | `/api/races?team_id=xxx&limit=20` | 公开 | 查询某队伍参与的历史记录 |

创建后写入 `races` 表（`type='test'`, `status='waiting'`），由 `services/test_worker.py` 中的 `_race_event_worker_loop` 消费执行。

---

## `blueprints/recording.py`

**职责**：录像元数据与遥测流。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET`  | `/api/recordings` | 扫描 `RECORDINGS_DIR`，返回所有含 `metadata.json` 的录像摘要 |
| `GET`  | `/api/recordings/{session_id}/metadata` | 返回 `metadata.json` 内容 |
| `GET`  | `/api/recordings/{session_id}/telemetry` | 流式返回 `telemetry.jsonl`（`application/x-ndjson`） |

录像目录结构：
```
recordings/{session_id}/
    ├── metadata.json      # 比赛结果、最终排名、队伍信息
    └── telemetry.jsonl    # NDJSON 遥测帧序列
```

---

## `blueprints/team.py`

**职责**：公共只读数据与队伍注册。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET`  | `/api/zones` | 所有赛区列表（公开） |
| `GET`  | `/api/zones/{zone_id}` | 赛区详情（队伍、积分榜、赛制） |
| `GET`  | `/api/zones/{zone_id}/status` | 实时阶段与 running_session_id |
| `GET`  | `/api/zones/{zone_id}/qualifying-results` | 排位赛结果 |
| `GET`  | `/api/teams?zone_id=xxx` | 队伍列表（可按赛区过滤） |
| `POST` | `/api/register` | 队伍自注册（zone_id, team_id, team_name, password） |

---

## `ws/admin.py`

**职责**：向管理后台推送实时仿真状态。

```
WS /ws/admin
```

**连接后行为**：立即发送所有已知赛区的最后一条状态消息，确保前端切换赛区时无需等待。

**消息格式**：

```json
{
  "type": "sim_status",
  "zone_id": "cs",
  "state": "PLACEMENT_RUNNING",
  "session_id": "cs_placement_1_1234567890",
  "session_type": "placement",
  "webots_pid": 12345,
  "sim_time": 45.3,
  "recording_path": "/path/to/recordings/...",
  "vehicles": { ... }
}
```

| `state` 值 | 含义 |
|-----------|------|
| `REGISTRATION` | 报名阶段，允许提交代码 |
| `IDLE` | 待命，等待管理员操作 |
| `PLACEMENT_RUNNING` / `GROUP_STAGE_RUNNING` / `SEMI_RUNNING` / `FINAL_RUNNING` | 仿真进行中 |
| `PLACEMENT_FINISHED` / `GROUP_STAGE_FINISHED` / `SEMI_FINISHED` / `FINAL_FINISHED` | 单场比赛正常结束 |
| `RECORDING_READY` | 录像已就绪，结果已写入数据库 |
| `ABORTED` | 比赛被强制终止 |
| `CLOSED` | 赛事已关闭 |

> 注：后端广播时直接发送状态机枚举值的大写字符串。前端若需小写展示，会自行转换。

---

**最后更新**：2026-05-20

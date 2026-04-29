# Backend 蓝图文档


## 架构概述

Backend 采用 FastAPI，路由以 **APIRouter** 组织。
各 Router 在 `server/app.py` 中统一注册。

```
server/
├── app.py               # 注册所有 router
├── blueprints/
│   ├── submission.py    # 学生代码提交
│   ├── admin.py         # 助教控制台
│   └── recording.py     # 录像浏览
├── ws/
│   └── admin.py         # Admin WebSocket 推流
```

---

## `blueprints/submission.py`

**职责**：接收学生提交、执行即时合规检查、维护测试队列。


| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/submit` | 提交代码（Basic Auth） |
| `GET` | `/api/teams` | 列出所有队伍（公开） |
| `GET` | `/api/test-status/{team_id}` | 查询测试状态（Basic Auth） |

**即时合规检查流程：**

1. 密码验证
2. Base64 解码
3. `py_compile` 语法检查
4. 导入模块检查（`control` 函数必须存在）
5. Mock 调用：`control(dummy_l, dummy_r, 0.0)` 检查返回值
6. 通过后：写入文件系统 + 写入数据库 + 加入测试队列

**测试队列：**

- 内存队列（FIFO），单独 worker 线程消费
- 比赛进行中（state_machine 为 `*_RUNNING` 状态）时暂停消费
- 同一队伍有等待中的旧任务时，新提交替换旧任务
- 执行时调用 Sim Node：`POST /race/create`（`session_type="test"`，单车）

---

## `blueprints/admin.py`

**职责**：助教控制台，管理赛事推进、仿真启动与停止。

对应 Avalon `admin.py`。

所有路由需通过 HTTP Basic Auth（`Authorization: Basic <base64(admin:password)>`）。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/admin/set-session` | 配置下一场赛次（race_id、session_type 等） |
| `POST` | `/api/admin/start-race` | 启动仿真（调用 Sim Node `/race/create`） |
| `POST` | `/api/admin/stop-race` | 强制终止（调用 Sim Node `/race/{id}/cancel`） |
| `POST` | `/api/admin/reset-track` | 重置状态机至 IDLE |
| `POST` | `/api/admin/lock-submissions` | 锁定提交（不可逆，需二次确认） |
| `POST` | `/api/admin/finalize-qualifying` | 结算排位赛，写入积分 |
| `POST` | `/api/admin/finalize-group` | 结算分组赛 |
| `POST` | `/api/admin/finalize-semi` | 结算半决赛 |
| `POST` | `/api/admin/close-event` | 关闭赛事 |
| `GET` | `/api/standings` | 获取当前积分榜 |
| `GET` | `/api/admin/sim-status` | 查询当前 Sim Node 状态 |

---

## `blueprints/recording.py`

**职责**：为前端提供录像浏览和遥测流下载。

对应 Avalon `visualizer.py`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/recordings` | 列出所有已完成录像摘要 |
| `GET` | `/api/recordings/{session_id}/metadata` | 获取场次元数据 |
| `GET` | `/api/recordings/{session_id}/telemetry` | 流式下载 `telemetry.jsonl`（NDJSON） |

---

## `ws/admin.py`

**职责**：向助教控制台前端推送仿真状态变更。

对应 Avalon `socketio` 推送机制。

```
WS /ws/admin
```

**消息格式：**

```json
{
  "type":     "sim_status",
  "state":    "running",
  "race_id":  "group_race_G1",
  "sim_time": 45.3
}
```

| `state` 值 | 含义 |
|-----------|------|
| `"idle"` | 无仿真运行 |
| `"running"` | 仿真进行中 |
| `"recording_ready"` | 仿真正常结束，录像完整 |
| `"aborted"` | 仿真被强制终止 |

---

**最后更新**：2026-04-28

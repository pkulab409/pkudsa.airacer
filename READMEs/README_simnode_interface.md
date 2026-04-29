# Sim Node 接口文档

## `POST /race/create`

创建并启动一场仿真，对应 `BattleManager.start_battle()`。

### 请求体（JSON）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `race_id` | string | 是 | 比赛唯一 ID（格式见下） |
| `session_type` | string | 是 | 场次类型：`qualifying / group_race / semi / final / test` |
| `total_laps` | int | 是 | 总圈数 |
| `cars` | array | 是 | 参赛车辆列表 |

**`cars` 数组元素：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `car_slot` | string | 车辆插槽编号（`"car_1"` ~ `"car_4"`） |
| `team_id` | string | 队伍 ID |
| `team_name` | string | 队伍名称（显示用） |
| `code_b64` | string | Base64 编码的 `team_controller.py` 源码 |

### 请求体示例

```json
{
  "race_id":      "group_race_G1",
  "session_type": "group_race",
  "total_laps":   3,
  "cars": [
    {
      "car_slot":   "car_1",
      "team_id":    "A01",
      "team_name":  "超级赛车队",
      "code_b64":   "<Base64 编码的源码>"
    }
  ]
}
```

### 响应体

```json
{
  "status":        "started",
  "race_id":       "group_race_G1",
  "stream_ws_url": "ws://192.168.1.100:8001/race/group_race_G1/stream"
}
```

Backend 收到响应后立即用 `stream_ws_url` 建立 WebSocket 连接，接收实时遥测推流。

---

## `POST /race/{race_id}/cancel`

终止正在运行的仿真，对应 `BattleManager.cancel_battle()`。

在 Linux 上发送 SIGKILL 终止 Webots 进程。

**响应：**

```json
{ "status": "cancelled", "race_id": "group_race_G1" }
```

---

## `GET /race/{race_id}/status`

查询比赛状态，对应 `BattleManager.get_battle_status()`。

**响应：**

```json
{ "race_id": "group_race_G1", "status": "running" }
```

| `status` 值 | 含义 |
|-------------|------|
| `"waiting"` | 已创建，等待启动 |
| `"running"` | 仿真进行中 |
| `"completed"` | 正常结束，结果可取 |
| `"error"` | 异常结束（Webots 崩溃等） |
| `"cancelled"` | 被 cancel 接口终止 |

---

## `GET /race/{race_id}/result`

获取已完成比赛的最终结果，对应 `BattleManager.get_battle_result()`。

**仅 `status == "completed"` 时可用，否则返回 HTTP 425。**

**响应：**

```json
{
  "race_id":        "group_race_G1",
  "session_type":   "group_race",
  "finish_reason":  "race_end",
  "duration_sim":   326.4,
  "total_frames":   5100,
  "final_rankings": [
    {"rank": 1, "team_id": "A01", "total_time": 321.4, "laps_completed": 3},
    {"rank": 2, "team_id": "C03", "total_time": null,  "laps_completed": 2}
  ]
}
```

---

## `GET /races`

列出所有比赛及状态，对应 `BattleManager.get_all_battles()`。

**响应：**

```json
[
  {"race_id": "group_race_G1", "status": "completed"},
  {"race_id": "test_A01_20260410_153021", "status": "running"}
]
```

---

## `WS /race/{race_id}/stream`

实时推送遥测帧到 Backend（Observer 的网络化版本）。

Backend 在调用 `/race/create` 后立即连接此端点，接收 JSON 消息。

### 消息格式

每条消息是一个 JSON 对象，结构与 `TelemetryObserver.make_snapshot()` 的快照完全一致：

```json
{
  "race_id":    "group_race_G1",
  "timestamp":  "2026-04-28 15:30:45",
  "event_type": "TelemetryFrame",
  "event_data": { ... }
}
```

### 消息类型（`event_type`）

| `event_type` | 触发时机 | Avalon 类比 |
|--------------|---------|-------------|
| `"TelemetryFrame"` | 每 64ms（仿真步） | `"Move"` |
| `"LapComplete"` | 某队完成整圈 | `"MissionResult"` |
| `"Collision"` | 碰撞事件 | `"Event"` |
| `"PowerupPick"` | 拾取加速包 | `"Event"` |
| `"LeaderFinished"` | 第一辆完赛，宽限期开始 | `"Big_Event"` |
| `"RaceEnd"` | 比赛正式结束 | `"GameEnd"` |
| `"race_error"` | Webots 崩溃等异常 | `"Bug"` |
| `"heartbeat"` | 服务端 30s 心跳 | — |

详细 `event_data` 格式见 `READMEs/README_telemetry.md`。

---

## `race_id` 格式规范

| 场次类型 | 格式 | 示例 |
|----------|------|------|
| 排位赛第 N 批 | `qualifying_{N}` | `qualifying_3` |
| 分组赛第 X 组 | `group_race_{G}` | `group_race_G1` |
| 半决赛第 N 场 | `semi_{N}` | `semi_2` |
| 决赛 | `final` | `final` |
| 学生测试 | `test_{team_id}_{YYYYMMDD_HHMMSS}` | `test_A01_20260410_153021` |

---

**最后更新**：2026-04-28

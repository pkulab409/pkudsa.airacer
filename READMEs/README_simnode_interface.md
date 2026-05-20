# Sim Node 接口文档

## `POST /race/create`

创建并启动一场仿真。

### 请求体（JSON）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `race_id` | string | 是 | 比赛唯一 ID |
| `session_type` | string | 是 | `placement / group_stage / semi / final / test` |
| `total_laps` | int | 是 | 总圈数 |
| `cars` | array | 是 | 参赛车辆列表 |

**`cars` 数组元素：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `car_slot` | string | 车辆插槽（`car_1` ~ `car_4`） |
| `team_id` | string | 队伍 ID |
| `team_name` | string | 队伍名称（显示用） |
| `code_b64` | string | Base64 编码的 `team_controller.py` 源码；空字符串表示无提交（车辆静止） |

> **注意**：`world` 场景文件由 SimNode 配置文件中的 `WEBOTS_WORLD` 决定，当前版本不支持通过 API 动态切换。

### 响应体

```json
{
  "status":        "started",
  "race_id":       "group_race_G1",
  "stream_ws_url": "ws://localhost:5000/race/group_race_G1/stream"
}
```

---

## `POST /race/{race_id}/cancel`

终止正在运行的仿真。先写入 `STOP` 信号文件尝试优雅退出，超时后强制 kill。

**响应：**

```json
{ "status": "cancelled", "race_id": "group_race_G1" }
```

---

## `GET /race/{race_id}/status`

查询比赛状态。

**响应：**

```json
{ "race_id": "group_race_G1", "status": "running" }
```

| `status` 值 | 含义 |
|-------------|------|
| `waiting` | 已创建，等待启动 |
| `running` | 仿真进行中 |
| `completed` | 正常结束，结果可取 |
| `error` | 异常结束 |
| `cancelled` | 被 cancel 接口终止 |

---

## `GET /race/{race_id}/result`

获取已完成比赛的最终结果。

**仅 `status == "completed"` 时可用，否则返回 HTTP 425。**

**响应：**

```json
{
  "session_id":        "group_race_G1",
  "session_type":      "group_stage",
  "finish_reason":     "grace_period_expired",
  "duration_sim":      326.4,
  "total_frames":      5100,
  "teams":             [{"team_id":"A01","team_name":"队1"}],
  "final_rankings":    [
    {"rank":1,"team_id":"A01","laps":3,"best_lap":42.5,"total_time":321.4,"status":"normal","collision_major_count":0},
    {"rank":2,"team_id":"B02","laps":3,"best_lap":43.1,"total_time":329.5,"status":"normal","collision_major_count":1}
  ]
}
```

---

## `GET /race/{race_id}/live`

获取实时比赛信息（热路径，读内存缓存）。

**响应：**

```json
{
  "race_id":    "group_race_G1",
  "webots_pid": 12345,
  "sim_time":   45.3,
  "cars": [
    {
      "team_id":    "A01",
      "x":          14.1,
      "y":          -3.5,
      "heading":    1.60,
      "speed":      8.3,
      "lap":        1,
      "lap_progress": 0.50,
      "checkpoints_passed": 2,
      "status":     "normal"
    }
  ]
}
```

---

## `GET /race/{race_id}/frame`

获取俯视摄像头最新 JPEG 帧（热路径，读内存缓存）。

**响应：** `image/jpeg` 二进制数据。

---

## `POST /race/{race_id}/push`

由 Webots supervisor 直接推送遥测数据到内存缓存，绕过磁盘 I/O。

**请求体：**

```json
{
  "t":         45.3,
  "cars":      [ ... ],
  "frame_b64": "<base64 JPEG>"   // 可选
}
```

---

## `GET /races`

列出所有比赛及状态。

**响应：**

```json
[
  {"race_id": "group_race_G1", "status": "completed"},
  {"race_id": "test_A01_20260410_153021", "status": "running"}
]
```

---

## `WS /race/{race_id}/stream`

实时推送遥测事件。

Backend 在调用 `/race/create` 后可选连接此端点接收事件。

### 消息格式

```json
{
  "race_id":    "group_race_G1",
  "timestamp":  "2026-04-28 15:30:45",
  "event_type": "race_event",
  "event_data": { ... }
}
```

### 事件类型

| `event_type` | 触发时机 |
|--------------|---------|
| `race_event` | 常规事件（RaceStart, TelemetrySnapshot 等） |
| `race_ended` | 比赛结束（含 reason、final_rankings） |

---

## `GET /health`

健康检查。

**响应：** `{"status": "ok", "service": "simnode"}`

---

## `race_id` 格式规范

| 场次类型 | 格式示例 |
|----------|----------|
| 排位赛 | `cs_placement_1_1234567890` |
| 小组赛 | `cs_group_stage_1_1234567890` |
| 半决赛 | `cs_semi_1_1234567890` |
| 决赛 | `cs_final_1_1234567890` |
| 学生测试 | `test_teamA_20260410_153021` |
| 统一测试赛事 | `race_{uuid[:8]}` |

---

**最后更新**：2026-05-20

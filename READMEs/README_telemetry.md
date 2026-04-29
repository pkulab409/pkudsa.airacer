# 遥测数据格式文档

## 1. 快照结构

每条快照（由 `TelemetryObserver.make_snapshot(event_type, event_data)` 生成）的完整结构：

```json
{
  "race_id":    "group_race_G1",
  "timestamp":  "2026-04-28 15:30:45",
  "event_type": "TelemetryFrame",
  "event_data": { ... }
}
```

与 Avalon `observer.py` 的快照字段对比：

| Avalon | AiRacer | 说明 |
|--------|---------|------|
| `battle_id` | `race_id` | 对局唯一 ID |
| `player_count` | （无） | AiRacer 改用 `cars` 数组 |
| `map_size` | （无） | 地图由 Webots 世界文件定义 |
| `timestamp` | `timestamp` | 相同 |
| `event_type` | `event_type` | 相同 |
| `event_data` | `event_data` | 相同 |

---

## 2. `event_type` 与 `event_data` 对应关系

### `"TelemetryFrame"` — 实时遥测帧

对应 Avalon `"Move"` 事件（玩家位置字典）。每 64ms 发送一次。

```json
{
  "t":    45.312,
  "cars": [
    {
      "team_id":         "A01",
      "x":               14.1,
      "y":               -3.5,
      "heading":         1.60,
      "speed":           8.3,
      "lap":             1,
      "lap_progress":    0.50,
      "status":          "normal",
      "boost_remaining": 0.0
    }
  ]
}
```

- `heading`：弧度，范围 $[-\pi, +\pi]$，以 $+X$ 轴为 0，逆时针递增
- `lap_progress`：见下方数据字典
- `status` 枚举：`normal / stopped / disqualified`

---

### `"LapComplete"` — 完成整圈

对应 Avalon `"MissionResult"` 事件。

```json
{
  "team_id":    "A01",
  "lap_number": 2,
  "lap_time":   42.317
}
```

---

### `"Collision"` — 碰撞事件

对应 Avalon `"Event"` 事件。

```json
{
  "team_id":       "A01",
  "severity":      "major",
  "collision_with": "barrier"
}
```

- `severity`：`"minor"`（轻微，无惩罚）或 `"major"`（严重，停车 2 秒）
- `collision_with`：`"barrier"` / `"car_{team_id}"`

---

### `"PowerupPick"` — 拾取加速包

```json
{
  "team_id":       "A01",
  "powerup_id":    "boost_3",
  "effect_duration": 5.0
}
```

---

### `"TimeoutWarn"` — 控制函数超时警告

```json
{
  "team_id":   "A01",
  "warn_count": 2
}
```

`warn_count` 达到 3 时，该队本圈作废（Supervisor 不计入排名）。

---

### `"ObstacleSpawn"` / `"ObstacleRemove"` — 动态障碍物

```json
{ "obstacle_id": "cone_7", "x": 3.2, "y": -1.5 }
```

---

### `"LeaderFinished"` — 领先者完赛，宽限期开始

对应 Avalon `"Big_Event"`。

```json
{
  "team_id":      "C03",
  "finish_time":  318.2,
  "grace_end_time": 378.2
}
```

---

### `"RaceEnd"` — 比赛正式结束

对应 Avalon `"GameEnd"`。

```json
{
  "reason":          "race_end",
  "final_rankings": [
    {"rank": 1, "team_id": "C03", "total_time": 318.2, "laps_completed": 3},
    {"rank": 2, "team_id": "A01", "total_time": 329.5, "laps_completed": 3},
    {"rank": 3, "team_id": "B02", "total_time": null,  "laps_completed": 2}
  ]
}
```

`reason` 枚举：

| 值 | 含义 |
|----|------|
| `"race_end"` | 宽限期结束，正常结束 |
| `"timeout"` | 达到最长仿真时间 |
| `"all_disqualified"` | 所有车辆均被取消资格 |

---

### `"race_error"` — 仿真异常

对应 Avalon `"Bug"` 事件。

```json
{
  "error_type": "webots_crash",
  "message":    "Webots 进程以退出码 139 崩溃"
}
```

---

## 3. 存储格式

遥测数据以 **NDJSON** 格式（每行一个 JSON 对象）存储在：

```
recordings/{race_id}/telemetry.jsonl
```

对应 Avalon `archive_game_{id}.json`（Avalon 是整个一个 JSON 数组，AiRacer 改为逐行追加，支持未完成对局的数据保全）。

---

## 4. `lap_progress` 数据字典

| 位置 | `k`（已通过检查点数） | 值 |
|------|---------------------|-----|
| 过 CP0，未到 CP1 | 0 | 0.00 |
| 过 CP0→CP1 | 1 | 0.25 |
| 过 CP0→CP1→CP2 | 2 | 0.50 |
| 过 CP0→CP1→CP2→CP3 | 3 | 0.75 |

---

**最后更新**：2026-04-28

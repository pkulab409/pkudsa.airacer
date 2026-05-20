# 遥测数据格式文档

## 1. 存储格式

遥测数据以 **NDJSON** 格式（每行一个 JSON 对象）存储在：

```
recordings/{session_id}/telemetry.jsonl
```

每行代表一帧仿真数据，由 Supervisor 在每一步直接追加写入。

---

## 2. 帧结构

```json
{
  "t":      45.312,
  "cars":   [ ... ],
  "events": [ ... ]
}
```

### `cars` 数组元素

| 字段 | 类型 | 说明 |
|------|------|------|
| `team_id` | string | 队伍 ID |
| `x` | float | 世界坐标 X（ENU） |
| `y` | float | 世界坐标 Y（ENU） |
| `heading` | float | 朝向弧度，[-pi, +pi]，+X 轴为 0 |
| `speed` | float | 当前速度（m/s） |
| `lap` | int | 已完成圈数 |
| `lap_progress` | float | 当前检查点进度（`checkpoint_next * 0.25`，每圈归零） |
| `checkpoints_passed` | int | 累计通过检查点次数 |
| `status` | string | `normal / stopped / disqualified / finished / idle` |
| `boost_remaining` | float | 加速包剩余时间（秒） |

> **注意**：`lap_progress` 按检查点索引乘以 0.25 计算，每完成一圈后归零重新累加，因此单圈内的取值范围为 **0.00 ~ 2.00**（取决于检查点数量）。

### `events` 数组元素

| `type` | 字段 | 说明 |
|--------|------|------|
| `lap_start` | `team_id`, `sim_time` | 车辆首次通过 CP0，开始计时 |
| `checkpoint` | `team_id`, `checkpoint_id`, `sim_time` | 通过中间检查点 |
| `lap_complete` | `team_id`, `lap_number`, `lap_time`, `best_lap_time` | 完成一整圈 |
| `car_finished` | `team_id`, `finish_time`, `total_laps` | 车辆完成全部圈数 |
| `leader_finished` | `team_id`, `finish_time`, `grace_end_time` | 首车完赛，宽限期开始 |
| `race_end` | `reason`, `final_rankings` | 比赛正式结束 |
| `collision` | `severity`, `team_ids`, `distance`, `rel_speed`, `sim_time` | 车辆间碰撞 |
| `disqualified` | `team_id`, `reason`, `sim_time` | 车辆被取消资格 |

### `race_end` 的 `reason` 枚举

| 值 | 含义 |
|----|------|
| `grace_period_expired` | 宽限期结束，正常结束 |
| `global_timeout` | 达到 120 秒全局超时（非排位赛） |
| `all_cars_done` | 所有车辆均完赛/违规/停止 |
| `timeout` | 达到 600 秒全局超时 |
| `admin_stop` | 管理员手动停止 |

---

## 3. 元数据（metadata.json）

比赛结束后，Supervisor 写入：

```
recordings/{session_id}/metadata.json
```

```json
{
  "session_id":       "cs_group_stage_1_1234567890",
  "session_type":     "group_stage",
  "total_laps":       3,
  "recording_path":   "./recordings/cs_group_stage_1_1234567890",
  "recorded_at":      "2026-05-20T14:30:00",
  "duration_sim":     326.4,
  "total_frames":     5100,
  "teams":            [{"team_id":"A01","team_name":"队1"}],
  "finish_reason":    "grace_period_expired",
  "final_rankings":   [
    {"rank":1,"team_id":"A01","team_name":"队1","laps":3,"best_lap":42.5,"total_time":321.4,"status":"normal","collision_major_count":0}
  ]
}
```

---

## 4. 实时缓存文件（供 SimNode 热路径读取）

- `live.json`：原子写入的当前帧摘要（`t`, `cars`），每 2 步更新
- `live_view.jpg`：俯视摄像头 JPEG，每 2 步保存

---

**最后更新**：2026-05-20

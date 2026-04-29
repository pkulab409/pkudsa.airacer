# 数据库文档


## 1. 技术选型

- **数据库引擎**：SQLite（与 Avalon 相同，可按需切换）
- **ORM**：原生 `sqlite3`（无 ORM，直接 SQL）
- **文件位置**：`server/database/race.db`

与 Avalon 的对比：
- Avalon 使用 Flask-SQLAlchemy ORM（`database/models.py` 定义类）
- AiRacer 使用原生 `sqlite3` + `server/database/action.py` 封装 CRUD
  这与 Avalon `database/action.py` 的封装思路完全一致，只是去掉了 ORM 层

---

## 2. 数据模型

### 2.1 `teams`（对应 Avalon `User`）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 队伍 ID（如 `A01`） |
| `name` | TEXT | 队伍名称 |
| `password_hash` | TEXT | bcrypt 哈希 |
| `created_at` | TEXT | 注册时间（ISO 8601） |

### 2.2 `submissions`（对应 Avalon `AICode`）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `team_id` | TEXT | 外键 → `teams.id` |
| `code_path` | TEXT | 文件系统路径 |
| `submitted_at` | TEXT | 提交时间 |
| `is_active` | INTEGER | 1 = 当前有效，0 = 已被新版本替代 |

### 2.3 `test_runs`（Avalon 无对应）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | — |
| `submission_id` | TEXT | 外键 → `submissions.id` |
| `status` | TEXT | `queued / running / done / skipped` |
| `queued_at` | TEXT | 入队时间 |
| `started_at` | TEXT | 开始时间 |
| `finished_at` | TEXT | 完成时间 |
| `laps_completed` | INTEGER | 完成圈数 |
| `best_lap_time` | REAL | 最快单圈时间（秒） |
| `collisions_minor` | INTEGER | 轻微碰撞次数 |
| `collisions_major` | INTEGER | 严重碰撞次数 |
| `timeout_warnings` | INTEGER | 超时警告次数 |
| `finish_reason` | TEXT | 测试结束原因 |

### 2.4 `race_sessions`（对应 Avalon `Battle`）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | `race_id` |
| `type` | TEXT | `qualifying / group_race / semi / final / test` |
| `team_ids` | TEXT | JSON 数组字符串 |
| `total_laps` | INTEGER | 总圈数 |
| `started_at` | TEXT | 开始时间 |
| `finished_at` | TEXT | 结束时间 |
| `phase` | TEXT | `running / finished / aborted` |
| `result` | TEXT | JSON 字符串（`final_rankings` 等） |

### 2.5 `race_points`（对应 Avalon `GameStats`）

| 列名 | 类型 | 说明 |
|------|------|------|
| `team_id` | TEXT | 复合 PK |
| `session_id` | TEXT | 复合 PK，外键 → `race_sessions.id` |
| `rank` | INTEGER | 本场排名 |
| `points` | INTEGER | 本场积分（名次积分表：1→10, 2→7, 3→5, 4→3） |

---

## 3. CRUD 接口（`database/action.py`）

与 Avalon `database/action.py` 完全相同的封装思路：blueprints/ 只调用函数，不写 SQL。

### Teams

| 函数 | 说明 |
|------|------|
| `create_team(team_id, name, password_hash)` | 注册新队伍 |
| `get_team(team_id) → Optional[Dict]` | 查询队伍信息 |
| `list_teams() → List[Dict]` | 列出所有队伍 |

### Submissions

| 函数 | 说明 |
|------|------|
| `create_submission(team_id, code_path, submitted_at) → str` | 创建提交，返回 `submission_id` |
| `get_active_submission(team_id) → Optional[Dict]` | 获取当前有效提交 |

### TestRuns

| 函数 | 说明 |
|------|------|
| `create_test_run(submission_id, queued_at) → int` | 创建测试记录，返回 `id` |
| `update_test_run(test_run_id, **kwargs)` | 更新测试结果 |
| `get_latest_test_run(submission_id) → Optional[Dict]` | 获取最新测试报告 |

### RaceSessions

| 函数 | 说明 |
|------|------|
| `create_race_session(race_id, ...)` | 创建比赛记录 |
| `update_race_session(race_id, **kwargs)` | 更新比赛状态/结果 |
| `get_race_session(race_id) → Optional[Dict]` | 查询比赛 |

### RacePoints

| 函数 | 说明 |
|------|------|
| `upsert_race_points(race_id, team_id, rank, points)` | 写入/更新积分 |
| `get_standings() → List[Dict]` | 获取总积分榜 |

---

**最后更新**：2026-04-28

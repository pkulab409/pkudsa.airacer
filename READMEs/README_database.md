# 数据库文档

## 1. 技术选型

- **数据库引擎**：SQLite
- **ORM**：原生 `sqlite3`（无 ORM，直接 SQL）
- **文件位置**：由 `config.py` 中的 `DB_PATH` 决定（默认 `server/database/race.db`）
- **连接方式**：`database/models.py` 提供 `get_db()` 上下文管理器（自动提交/回滚）

---

## 2. 数据模型

### `zones` - 赛区

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 赛区 ID（如 `cs`、`experiment`） |
| `name` | TEXT | 赛区名称 |
| `description` | TEXT | 描述 |
| `total_laps` | INTEGER | 默认圈数 |
| `state` | TEXT | 持久化状态机值（默认 `REGISTRATION`） |
| `created_at` | TEXT | 创建时间（ISO 8601） |

### `teams` - 队伍

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | 队伍 ID（如 `A01`） |
| `name` | TEXT | 队伍名称 |
| `password_hash` | TEXT | bcrypt 哈希 |
| `zone_id` | TEXT FK -> zones.id | 所属赛区 |
| `created_at` | TEXT | 注册时间 |

### `submissions` - 代码提交

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `team_id` | TEXT FK | 所属队伍 |
| `code_path` | TEXT | 文件系统绝对路径 |
| `submitted_at` | TEXT | 提交时间戳 |
| `is_active` | INTEGER | 1 = 当前有效，0 = 已被替代 |
| `slot_name` | TEXT | `main` / `dev` / `backup` |
| `is_race_active` | INTEGER | 1 = 当前参赛版本 |

### `test_runs` - 测试运行记录

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | - |
| `submission_id` | TEXT FK | 关联提交 |
| `status` | TEXT | `queued / running / done / error / skipped` |
| `queued_at` | TEXT | 入队时间 |
| `started_at` | TEXT | 开始时间 |
| `finished_at` | TEXT | 完成时间 |
| `laps_completed` | INTEGER | 完成圈数 |
| `best_lap_time` | REAL | 最快单圈（秒） |
| `collisions_minor` | INTEGER | 轻微碰撞次数 |
| `collisions_major` | INTEGER | 严重碰撞次数 |
| `timeout_warnings` | INTEGER | 超时警告次数 |
| `finish_reason` | TEXT | 结束原因 |
| `world_key` | TEXT | `basic` / `complex`（默认 `complex`） |

### `race_sessions` - 正式比赛场次

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | `session_id` |
| `type` | TEXT | `placement / group_stage / semi / final / test` |
| `team_ids` | TEXT | JSON 数组字符串 |
| `total_laps` | INTEGER | 总圈数 |
| `started_at` | TEXT | 开始时间 |
| `finished_at` | TEXT | 结束时间 |
| `phase` | TEXT | `waiting / running / recording_ready / finished / aborted / cancelled` |
| `result` | TEXT | JSON 字符串（含 `final_rankings` 等） |
| `zone_id` | TEXT FK -> zones.id | 所属赛区 |
| `name` | TEXT | 可读名称（如"排位赛 第1场"） |

### `race_points` - 积分

| 列名 | 类型 | 说明 |
|------|------|------|
| `team_id` | TEXT PK | 复合主键 |
| `session_id` | TEXT PK | 复合主键，FK -> race_sessions.id |
| `rank` | INTEGER | 本场排名 |
| `points` | INTEGER | 本场积分（10/7/5/3/1） |
| `best_lap_time` | REAL | 本场最快单圈 |

### `races` - 统一赛事表（含测试赛）

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | `race_id`（UUID） |
| `type` | TEXT | `test` / 未来扩展正赛类型 |
| `zone_id` | TEXT FK | 所属赛区 |
| `initiator` | TEXT | 发起者 team_id |
| `participant_ids` | TEXT | JSON 数组字符串 |
| `status` | TEXT | `waiting / running / done / error / cancelled` |
| `world_key` | TEXT | `basic` / `complex` |
| `total_laps` | INTEGER | 圈数 |
| `created_at` | TEXT | 创建时间 |
| `started_at` | TEXT | 开始时间 |
| `finished_at` | TEXT | 结束时间 |
| `finish_reason` | TEXT | 结束原因 |
| `result` | TEXT | JSON 字符串 |
| `name` | TEXT | 自定义名称/备注 |

---

## 3. CRUD 接口（`database/action.py`）

### Zone

| 函数 | 说明 |
|------|------|
| `db_list_zones(conn) -> List[Dict]` | 列出所有赛区（含 team_count 聚合） |
| `db_get_zone(conn, zone_id) -> Optional[Dict]` | 查询单个赛区 |
| `db_create_zone(conn, id, name, description, total_laps, created_at)` | 创建赛区 |
| `db_delete_zone(conn, zone_id) -> bool` | 删除赛区及其关联数据 |
| `db_ensure_default_zone(conn, now)` | 幂等创建默认赛区 |
| `db_get_zone_teams(conn, zone_id) -> List[Dict]` | 赛区队伍（含 active_slot） |
| `db_get_zone_standings(conn, zone_id) -> List[Dict]` | 赛区积分榜 |
| `db_get_zone_team_count(conn, zone_id) -> int` | 队伍数 |
| `db_get_zone_detailed(conn, zone_id) -> Optional[Dict]` | 完整详情（队伍+积分榜） |

### Session Preparation

| 函数 | 说明 |
|------|------|
| `db_get_zone_team_ids(conn, zone_id) -> List[str]` | 获取赛区所有队伍 ID |
| `db_get_teams_with_code(conn, team_ids) -> List[Dict]` | 获取队伍及代码路径（优先 race_active，回退 main） |
| `db_upsert_session(conn, session_id, type, team_ids, total_laps, zone_id, name)` | 创建/重置场次 |
| `db_get_waiting_session(conn, zone_id) -> Optional[Dict]` | 取下一个 waiting 场次 |
| `db_mark_session_running(conn, session_id, started_at)` | 标记 running |
| `db_get_running_session(conn, zone_id) -> Optional[Dict]` | 查询当前 running 场次 |
| `db_mark_session_finished(conn, session_id, now)` | 标记 recording_ready |
| `db_mark_session_aborted(conn, session_id, phase, now)` | 标记 aborted / recording_ready |

### Teams

| 函数 | 说明 |
|------|------|
| `create_team(conn, team_id, name, password_hash, zone_id)` | 注册队伍 |
| `get_team(conn, team_id) -> Optional[Dict]` | 查询队伍 |
| `db_get_team_secure(conn, team_id) -> Optional[Dict]` | 查询队伍（含 password_hash、zone_id） |
| `list_teams(conn) -> List[Dict]` | 列出所有队伍 |

### Submissions

| 函数 | 说明 |
|------|------|
| `db_create_submission_with_slot(conn, team_id, code_path, slot_name, submitted_at) -> str` | 创建提交（自动处理 is_race_active） |
| `db_get_submission_by_slot(conn, team_id, slot_name) -> Optional[Dict]` | 查询槽位最新提交 |
| `db_get_submission_by_id(conn, submission_id) -> Optional[Dict]` | 按 ID 查询 |
| `db_activate_submission_slot(conn, team_id, slot_name) -> bool` | 激活参赛槽位 |

### TestRuns

| 函数 | 说明 |
|------|------|
| `create_test_run(conn, submission_id, queued_at, world_key) -> int` | 创建测试记录 |
| `update_test_run(conn, test_run_id, **kwargs)` | 更新测试结果 |
| `get_latest_test_run(conn, submission_id) -> Optional[Dict]` | 最新测试记录 |

### RaceSessions

| 函数 | 说明 |
|------|------|
| `create_race_session(conn, race_id, type, team_ids, total_laps, phase, started_at)` | 创建场次 |
| `update_race_session(conn, race_id, **kwargs)` | 更新状态/结果 |
| `get_race_session(conn, race_id) -> Optional[Dict]` | 查询场次 |

### RacePoints

| 函数 | 说明 |
|------|------|
| `upsert_race_points(conn, race_id, team_id, rank, points, best_lap_time)` | 写入/更新积分 |
| `get_standings(conn) -> List[Dict]` | 全局积分榜 |

### Races (Unified)

| 函数 | 说明 |
|------|------|
| `create_race(conn, race_id, type, zone_id, initiator, participant_ids, world_key, total_laps, name, created_at)` | 创建赛事 |
| `update_race(conn, race_id, **kwargs)` | 更新赛事 |
| `get_race(conn, race_id) -> Optional[Dict]` | 查询赛事 |
| `list_races_by_participant(conn, team_id, limit) -> List[Dict]` | 按参与者查询 |

---

**最后更新**：2026-05-20

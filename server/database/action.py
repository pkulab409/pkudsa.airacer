"""
database/action.py — 数据库 CRUD 操作封装，对应 Avalon 的 database/action.py

职责：将所有原始 SQL 语句集中封装，使 blueprints/ 中的代码只调用函数，
不直接写 SQL（与 Avalon 的设计完全一致）。
"""

import datetime
import uuid
from typing import Any, Dict, List, Optional

from .models import get_db
from server.config.config import Config

DB_PATH = Config.get("DB_PATH")


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def create_team(team_id: str, name: str, password_hash: str) -> None:
    with get_db(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO teams (id, name, password_hash) VALUES (?, ?, ?)",
            (team_id, name, password_hash),
        )


def get_team(team_id: str) -> Optional[Dict]:
    with get_db(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, name, password_hash, created_at FROM teams WHERE id = ?",
            (team_id,),
        ).fetchone()
    return dict(row) if row else None


def list_teams() -> List[Dict]:
    with get_db(DB_PATH) as conn:
        rows = conn.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Submissions（对应 Avalon AICode）
# ---------------------------------------------------------------------------

def create_submission(team_id: str, code_path: str, submitted_at: str) -> str:
    """创建新提交，停用该队伍的历史提交，返回新 submission_id。"""
    submission_id = str(uuid.uuid4())
    with get_db(DB_PATH) as conn:
        conn.execute(
            "UPDATE submissions SET is_active = 0 WHERE team_id = ?",
            (team_id,),
        )
        conn.execute(
            """INSERT INTO submissions (id, team_id, code_path, submitted_at, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (submission_id, team_id, code_path, submitted_at),
        )
    return submission_id


def get_active_submission(team_id: str) -> Optional[Dict]:
    with get_db(DB_PATH) as conn:
        row = conn.execute(
            """SELECT id, team_id, code_path, submitted_at FROM submissions
               WHERE team_id = ? AND is_active = 1
               ORDER BY submitted_at DESC LIMIT 1""",
            (team_id,),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# TestRuns（Avalon 无对应，AiRacer 新增）
# ---------------------------------------------------------------------------

def create_test_run(submission_id: str, queued_at: str) -> int:
    with get_db(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO test_runs (submission_id, status, queued_at) VALUES (?, 'queued', ?)",
            (submission_id, queued_at),
        )
    return cur.lastrowid


def update_test_run(test_run_id: int, **kwargs) -> None:
    """动态更新 test_runs 的任意字段。"""
    allowed = {
        "status", "started_at", "finished_at",
        "laps_completed", "best_lap_time", "collisions_minor",
        "collisions_major", "timeout_warnings", "finish_reason",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values     = list(fields.values()) + [test_run_id]
    with get_db(DB_PATH) as conn:
        conn.execute(
            f"UPDATE test_runs SET {set_clause} WHERE id = ?",
            values,
        )


def get_latest_test_run(submission_id: str) -> Optional[Dict]:
    with get_db(DB_PATH) as conn:
        row = conn.execute(
            "SELECT * FROM test_runs WHERE submission_id = ? ORDER BY id DESC LIMIT 1",
            (submission_id,),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# RaceSessions（对应 Avalon Battle）
# ---------------------------------------------------------------------------

def create_race_session(
    race_id: str, session_type: str, team_ids: List[str],
    total_laps: int, phase: str, started_at: str,
) -> None:
    import json
    with get_db(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO race_sessions (id, type, team_ids, total_laps, phase, started_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (race_id, session_type, json.dumps(team_ids), total_laps, phase, started_at),
        )


def update_race_session(race_id: str, **kwargs) -> None:
    allowed = {"phase", "finished_at", "result"}
    fields  = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    if "result" in fields and not isinstance(fields["result"], str):
        import json; fields["result"] = json.dumps(fields["result"])
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values     = list(fields.values()) + [race_id]
    with get_db(DB_PATH) as conn:
        conn.execute(
            f"UPDATE race_sessions SET {set_clause} WHERE id = ?",
            values,
        )


def get_race_session(race_id: str) -> Optional[Dict]:
    import json
    with get_db(DB_PATH) as conn:
        row = conn.execute(
            "SELECT * FROM race_sessions WHERE id = ?",
            (race_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("team_ids"):
        d["team_ids"] = json.loads(d["team_ids"])
    return d


# ---------------------------------------------------------------------------
# RacePoints（对应 Avalon GameStats）
# ---------------------------------------------------------------------------

def upsert_race_points(race_id: str, team_id: str, rank: int, points: int) -> None:
    with get_db(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO race_points (team_id, session_id, rank, points)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_id, session_id) DO UPDATE SET rank=excluded.rank, points=excluded.points""",
            (team_id, race_id, rank, points),
        )


def get_standings() -> List[Dict]:
    """汇总各队总积分，对应 Avalon 的排行榜查询。"""
    with get_db(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT rp.team_id, t.name, SUM(rp.points) as total_points
               FROM race_points rp
               JOIN teams t ON rp.team_id = t.id
               GROUP BY rp.team_id
               ORDER BY total_points DESC"""
        ).fetchall()
    return [dict(r) for r in rows]

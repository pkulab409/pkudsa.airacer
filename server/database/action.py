"""
database/action.py — 数据库 CRUD 操作封装

职责：将所有原始 SQL 语句集中封装，使 blueprints/ 中的代码只调用函数，不直接写 SQL。
所有函数接受 conn 参数，不自行管理事务，由调用方通过 with get_db() 控制事务边界。
"""

import json
import uuid
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------


def db_list_zones(conn) -> List[Dict]:
    rows = conn.execute("""
        SELECT z.id, z.name, z.description, z.total_laps, z.created_at,
               COUNT(t.id) AS team_count
        FROM zones z
        LEFT JOIN teams t ON t.zone_id = z.id
        GROUP BY z.id
        ORDER BY z.created_at
    """).fetchall()
    return [dict(r) for r in rows]


def db_get_zone(conn, zone_id: str) -> Optional[Dict]:
    row = conn.execute(
        "SELECT id, name, total_laps FROM zones WHERE id=?", (zone_id,)
    ).fetchone()
    return dict(row) if row else None


def db_create_zone(conn, id: str, name: str, description: str, total_laps: int, created_at: str):
    conn.execute(
        "INSERT INTO zones (id, name, description, total_laps, created_at) VALUES (?,?,?,?,?)",
        (id, name, description, total_laps, created_at),
    )


def db_delete_zone(conn, zone_id: str) -> bool:
    row = conn.execute("SELECT id FROM zones WHERE id=?", (zone_id,)).fetchone()
    if row is None:
        return False
    conn.execute("DELETE FROM zones WHERE id=?", (zone_id,))
    return True


def db_ensure_default_zone(conn, now: str):
    conn.execute(
        "INSERT OR IGNORE INTO zones (id, name, description, total_laps, created_at) VALUES ('default','Default Zone','',3,?)",
        (now,),
    )


def db_get_zone_teams(conn, zone_id: str) -> List[Dict]:
    rows = conn.execute(
        """SELECT t.id, t.name, t.created_at,
                  s.slot_name AS active_slot,
                  s.submitted_at AS active_version
           FROM teams t
           LEFT JOIN submissions s
             ON s.team_id = t.id AND s.is_race_active = 1
           WHERE t.zone_id = ?
           ORDER BY t.name""",
        (zone_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def db_get_zone_standings(conn, zone_id: str) -> List[Dict]:
    rows = conn.execute(
        """SELECT rp.team_id, t.name, SUM(rp.points) AS total_points
           FROM race_points rp
           JOIN teams t ON rp.team_id = t.id
           JOIN race_sessions rs ON rp.session_id = rs.id
           WHERE rs.zone_id = ?
           GROUP BY rp.team_id
           ORDER BY total_points DESC""",
        (zone_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def db_get_zone_team_count(conn, zone_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM teams WHERE zone_id=?", (zone_id,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Zone session preparation
# ---------------------------------------------------------------------------


def db_get_zone_team_ids(conn, zone_id: str) -> List[str]:
    rows = conn.execute(
        "SELECT id FROM teams WHERE zone_id=? ORDER BY name", (zone_id,)
    ).fetchall()
    return [r["id"] for r in rows]


def db_get_teams_with_code(conn, team_ids: List[str]) -> List[Dict]:
    """
    Return [{id, name, code_path}] for the given team_ids, preserving order.
    code_path prefers race-active slot, falls back to main active slot.
    Raises ValueError listing any team_ids not found.
    """
    if not team_ids:
        return []
    placeholders = ",".join("?" * len(team_ids))
    rows = conn.execute(
        f"""SELECT t.id, t.name,
                   COALESCE(
                       (SELECT code_path FROM submissions
                        WHERE team_id=t.id AND is_race_active=1 AND is_active=1 LIMIT 1),
                       (SELECT code_path FROM submissions
                        WHERE team_id=t.id AND slot_name='main' AND is_active=1
                        ORDER BY submitted_at DESC LIMIT 1)
                   ) AS code_path
            FROM teams t
            WHERE t.id IN ({placeholders})""",
        team_ids,
    ).fetchall()
    found = {r["id"] for r in rows}
    missing = [tid for tid in team_ids if tid not in found]
    if missing:
        raise ValueError(f"Teams not found: {missing}")
    order = {tid: idx for idx, tid in enumerate(team_ids)}
    return sorted([dict(r) for r in rows], key=lambda r: order[r["id"]])


def db_upsert_session(
    conn, session_id: str, session_type: str,
    team_ids: List[str], total_laps: int, zone_id: str,
):
    conn.execute(
        """INSERT INTO race_sessions
               (id, type, team_ids, total_laps, started_at, finished_at, phase, result, zone_id)
               VALUES (?, ?, ?, ?, NULL, NULL, 'waiting', NULL, ?)
               ON CONFLICT(id) DO UPDATE SET
                 type=excluded.type, team_ids=excluded.team_ids,
                 total_laps=excluded.total_laps, phase='waiting',
                 started_at=NULL, finished_at=NULL, result=NULL,
                 zone_id=excluded.zone_id""",
        (session_id, session_type, json.dumps(team_ids), total_laps, zone_id),
    )


def db_get_waiting_session(conn, zone_id: str) -> Optional[Dict]:
    row = conn.execute(
        """SELECT id, type, total_laps FROM race_sessions
           WHERE phase='waiting' AND zone_id=?
           ORDER BY rowid DESC LIMIT 1""",
        (zone_id,),
    ).fetchone()
    return dict(row) if row else None

def db_get_all_waiting_sessions(conn, zone_id: str) -> list:
    rows = conn.execute(
        """SELECT id, type, total_laps, team_ids FROM race_sessions
           WHERE phase='waiting' AND zone_id=?
           ORDER BY rowid DESC""",
        (zone_id,),
    ).fetchall()
    return [dict(r) for r in rows]

def db_get_specific_waiting_session(conn, zone_id: str, session_id: str) -> dict | None:
    row = conn.execute(
        """SELECT id, type, total_laps FROM race_sessions
           WHERE phase='waiting' AND zone_id=? AND id=?""",
        (zone_id, session_id),
    ).fetchone()
    return dict(row) if row else None


def db_mark_session_running(conn, session_id: str, started_at: str):
    conn.execute(
        "UPDATE race_sessions SET phase='running', started_at=? WHERE id=?",
        (started_at, session_id),
    )


def db_get_running_session(conn, zone_id: str) -> Optional[Dict]:
    row = conn.execute(
        "SELECT id, type FROM race_sessions WHERE phase='running' AND zone_id=? ORDER BY rowid DESC LIMIT 1",
        (zone_id,),
    ).fetchone()
    return dict(row) if row else None


def db_mark_session_finished(conn, session_id: str, now: str):
    conn.execute(
        "UPDATE race_sessions SET phase='recording_ready', finished_at=? WHERE id=?",
        (now, session_id),
    )


def db_mark_session_aborted(conn, session_id: str, phase: str, now: str):
    conn.execute(
        "UPDATE race_sessions SET phase=?, finished_at=? WHERE id=?",
        (phase, now, session_id),
    )


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


def create_team(conn, team_id: str, name: str, password_hash: str) -> None:
    conn.execute(
        "INSERT INTO teams (id, name, password_hash) VALUES (?, ?, ?)",
        (team_id, name, password_hash),
    )


def get_team(conn, team_id: str) -> Optional[Dict]:
    row = conn.execute(
        "SELECT id, name, password_hash, created_at FROM teams WHERE id = ?",
        (team_id,),
    ).fetchone()
    return dict(row) if row else None


def list_teams(conn) -> List[Dict]:
    rows = conn.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


def create_submission(conn, team_id: str, code_path: str, submitted_at: str) -> str:
    submission_id = str(uuid.uuid4())
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


def get_active_submission(conn, team_id: str) -> Optional[Dict]:
    row = conn.execute(
        """SELECT id, team_id, code_path, submitted_at FROM submissions
               WHERE team_id = ? AND is_active = 1
               ORDER BY submitted_at DESC LIMIT 1""",
        (team_id,),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# TestRuns
# ---------------------------------------------------------------------------


def create_test_run(conn, submission_id: str, queued_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO test_runs (submission_id, status, queued_at) VALUES (?, 'queued', ?)",
        (submission_id, queued_at),
    )
    return cur.lastrowid


def update_test_run(conn, test_run_id: int, **kwargs) -> None:
    allowed = {
        "status", "started_at", "finished_at", "laps_completed",
        "best_lap_time", "collisions_minor", "collisions_major",
        "timeout_warnings", "finish_reason",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [test_run_id]
    conn.execute(f"UPDATE test_runs SET {set_clause} WHERE id = ?", values)


def get_latest_test_run(conn, submission_id: str) -> Optional[Dict]:
    row = conn.execute(
        "SELECT * FROM test_runs WHERE submission_id = ? ORDER BY id DESC LIMIT 1",
        (submission_id,),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# RaceSessions
# ---------------------------------------------------------------------------


def create_race_session(
    conn, race_id: str, session_type: str, team_ids: List[str],
    total_laps: int, phase: str, started_at: str,
) -> None:
    conn.execute(
        """INSERT INTO race_sessions (id, type, team_ids, total_laps, phase, started_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
        (race_id, session_type, json.dumps(team_ids), total_laps, phase, started_at),
    )


def update_race_session(conn, race_id: str, **kwargs) -> None:
    allowed = {"phase", "finished_at", "result"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    if "result" in fields and not isinstance(fields["result"], str):
        fields["result"] = json.dumps(fields["result"])
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [race_id]
    conn.execute(f"UPDATE race_sessions SET {set_clause} WHERE id = ?", values)


def get_race_session(conn, race_id: str) -> Optional[Dict]:
    row = conn.execute(
        "SELECT * FROM race_sessions WHERE id = ?", (race_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("team_ids"):
        d["team_ids"] = json.loads(d["team_ids"])
    return d


# ---------------------------------------------------------------------------
# RacePoints
# ---------------------------------------------------------------------------


def upsert_race_points(conn, race_id: str, team_id: str, rank: int, points: int) -> None:
    conn.execute(
        """INSERT INTO race_points (team_id, session_id, rank, points)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(team_id, session_id) DO UPDATE SET rank=excluded.rank, points=excluded.points""",
        (team_id, race_id, rank, points),
    )


def get_standings(conn) -> List[Dict]:
    rows = conn.execute(
        """SELECT rp.team_id, t.name, SUM(rp.points) as total_points
               FROM race_points rp
               JOIN teams t ON rp.team_id = t.id
               GROUP BY rp.team_id
               ORDER BY total_points DESC"""
    ).fetchall()
    return [dict(r) for r in rows]

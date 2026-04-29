"""
SQLite schema and helpers.  No ORM — raw sqlite3 only.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS teams (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS submissions (
    id           TEXT PRIMARY KEY,
    team_id      TEXT NOT NULL,
    code_path    TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS test_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id     TEXT NOT NULL,
    status            TEXT NOT NULL,
    queued_at         TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    laps_completed    INTEGER,
    best_lap_time     REAL,
    collisions_minor  INTEGER,
    collisions_major  INTEGER,
    timeout_warnings  INTEGER,
    finish_reason     TEXT
);

CREATE TABLE IF NOT EXISTS race_sessions (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    team_ids    TEXT NOT NULL,
    total_laps  INTEGER NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    phase       TEXT NOT NULL,
    result      TEXT
);

CREATE TABLE IF NOT EXISTS race_points (
    team_id    TEXT NOT NULL,
    session_id TEXT NOT NULL,
    rank       INTEGER,
    points     INTEGER,
    PRIMARY KEY (team_id, session_id)
);
"""


def init_db(db_path: str | Path) -> None:
    """Create all tables if they do not yet exist."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_DDL)
        conn.commit()


@contextmanager
def get_db(db_path: str | Path):
    """
    Context manager that yields an open sqlite3 connection with
    row_factory set to sqlite3.Row.

    Usage::

        with get_db(DB_PATH) as conn:
            row = conn.execute("SELECT * FROM teams WHERE id=?", (tid,)).fetchone()
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

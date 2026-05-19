"""
SQLite schema and helpers.  No ORM — raw sqlite3 only.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Union

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS zones (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    total_laps  INTEGER NOT NULL DEFAULT 3,
    state       TEXT NOT NULL DEFAULT 'REGISTRATION',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS teams (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    zone_id       TEXT REFERENCES zones(id)
);

CREATE TABLE IF NOT EXISTS submissions (
    id              TEXT PRIMARY KEY,
    team_id         TEXT NOT NULL,
    code_path       TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    slot_name       TEXT NOT NULL DEFAULT 'main',
    is_race_active  INTEGER NOT NULL DEFAULT 0
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
    finish_reason     TEXT,
    world_key         TEXT NOT NULL DEFAULT 'complex'
);

CREATE TABLE IF NOT EXISTS race_sessions (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    team_ids    TEXT NOT NULL,
    total_laps  INTEGER NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    phase       TEXT NOT NULL,
    result      TEXT,
    zone_id     TEXT REFERENCES zones(id),
    name        TEXT
);

CREATE TABLE IF NOT EXISTS race_points (
    team_id    TEXT NOT NULL,
    session_id TEXT NOT NULL,
    rank       INTEGER,
    points     INTEGER,
    best_lap_time REAL,
    PRIMARY KEY (team_id, session_id)
);

CREATE TABLE IF NOT EXISTS races (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    zone_id         TEXT NOT NULL REFERENCES zones(id),
    initiator       TEXT,
    participant_ids TEXT NOT NULL,
    status          TEXT NOT NULL,
    world_key       TEXT NOT NULL DEFAULT 'complex',
    total_laps      INTEGER NOT NULL DEFAULT 3,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    finish_reason   TEXT,
    result          TEXT,
    name            TEXT
);
"""

_MIGRATIONS = [
    # Idempotent ALTER TABLE statements for existing databases
    "ALTER TABLE teams       ADD COLUMN zone_id        TEXT REFERENCES zones(id)",
    "ALTER TABLE submissions ADD COLUMN slot_name       TEXT NOT NULL DEFAULT 'main'",
    "ALTER TABLE submissions ADD COLUMN is_race_active  INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE race_sessions ADD COLUMN zone_id       TEXT REFERENCES zones(id)",
    "ALTER TABLE zones       ADD COLUMN state           TEXT NOT NULL DEFAULT 'REGISTRATION'",
    "ALTER TABLE race_points ADD COLUMN best_lap_time REAL",
    "ALTER TABLE test_runs   ADD COLUMN world_key        TEXT NOT NULL DEFAULT 'complex'",
    "ALTER TABLE races      ADD COLUMN name             TEXT",
    "ALTER TABLE race_sessions ADD COLUMN name          TEXT",
]


def init_db(db_path: str | Path) -> None:
    """Create all tables if they do not yet exist, and run idempotent migrations."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_DDL)
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
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

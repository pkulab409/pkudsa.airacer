"""
Team submission and test-status endpoints.

POST /api/submit          — upload base64-encoded Python driver
GET  /api/teams           — list all teams (public)
GET  /api/test-status/{team_id} — latest test run status (Basic Auth)
"""

import asyncio
import base64
import datetime
import importlib.util
import os
import pathlib
import py_compile
import sys
import tempfile
import threading
import uuid
from typing import Optional

import bcrypt as _bcrypt
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from server.config.config import DB_PATH, SUBMISSIONS_DIR
from server.database.models import get_db

router = APIRouter()

# ---------------------------------------------------------------------------
# Password hashing (direct bcrypt, no passlib)
# ---------------------------------------------------------------------------

def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()

def _verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())

# ---------------------------------------------------------------------------
# Global submission lock (set by admin)
# ---------------------------------------------------------------------------

submissions_locked: bool = False

# ---------------------------------------------------------------------------
# In-memory test queue
# (Items: submission_id strings in order; worker pops from front)
# ---------------------------------------------------------------------------

_test_queue: list[str] = []
_test_queue_lock = threading.Lock()


def enqueue_test(submission_id: str) -> int:
    """Append submission_id to test queue. Returns 1-based queue position."""
    with _test_queue_lock:
        _test_queue.append(submission_id)
        return len(_test_queue)


def queue_position(submission_id: str) -> Optional[int]:
    """Return 1-based position in queue, or None if not found."""
    with _test_queue_lock:
        try:
            return _test_queue.index(submission_id) + 1
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Auth dependency for test-status
# ---------------------------------------------------------------------------

_basic_security = HTTPBasic()


def _require_team_auth(
    team_id: str,
    credentials: HTTPBasicCredentials = Depends(_basic_security),
) -> str:
    """
    Verify that the Basic Auth credentials match the given team_id.
    username must equal team_id; password is checked against the DB hash.
    """
    if credentials.username != team_id:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    with get_db(DB_PATH) as conn:
        row = conn.execute(
            "SELECT password_hash FROM teams WHERE id = ?", (team_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="Team not found")

    if not _verify_password(credentials.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return team_id


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SubmitRequest(BaseModel):
    team_id:  str
    password: str
    code:     str   # base64-encoded Python source


# ---------------------------------------------------------------------------
# POST /api/submit
# ---------------------------------------------------------------------------

@router.post("/api/submit")
async def submit_code(body: SubmitRequest):
    # 1. Check submission lock
    if submissions_locked:
        raise HTTPException(status_code=403, detail="Submissions are locked")

    # 2. Verify password
    with get_db(DB_PATH) as conn:
        team_row = conn.execute(
            "SELECT id, name, password_hash FROM teams WHERE id = ?",
            (body.team_id,),
        ).fetchone()

    if team_row is None:
        raise HTTPException(status_code=401, detail="Team not found")

    if not _verify_password(body.password, team_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    # 3. Decode base64
    try:
        code_bytes = base64.b64decode(body.code)
        code_str   = code_bytes.decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 code: {exc}")

    # 4a. Syntax check via py_compile (write to temp file first)
    with tempfile.NamedTemporaryFile(
        suffix=".py", delete=False, mode="w", encoding="utf-8"
    ) as tmp_src:
        tmp_src.write(code_str)
        tmp_path = tmp_src.name

    try:
        try:
            py_compile.compile(tmp_path, doraise=True)
        except py_compile.PyCompileError as exc:
            raise HTTPException(status_code=400, detail=f"Syntax error: {exc}")

        # 4b. Import check: ensure `control` callable exists and returns correct shape
        spec   = importlib.util.spec_from_file_location("_team_ctrl_check", tmp_path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Import error: {exc}")

        if not callable(getattr(module, "control", None)):
            raise HTTPException(
                status_code=400,
                detail="Module must define a callable named 'control'",
            )

        dummy_img1 = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy_img2 = np.zeros((480, 640, 3), dtype=np.uint8)
        dummy_time = 0.0
        try:
            result = module.control(dummy_img1, dummy_img2, dummy_time)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"control() raised an exception: {exc}"
            )

        if (
            not isinstance(result, (tuple, list))
            or len(result) != 2
            or not all(isinstance(v, (int, float)) for v in result)
        ):
            raise HTTPException(
                status_code=400,
                detail="control() must return a tuple of 2 floats",
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # 5. Save to submissions/{team_id}/{timestamp}/team_controller.py
    timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir    = pathlib.Path(SUBMISSIONS_DIR) / body.team_id / timestamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file   = dest_dir / "team_controller.py"
    dest_file.write_text(code_str, encoding="utf-8")

    submission_id = str(uuid.uuid4())

    # 6. Insert into DB, deactivate old submissions
    with get_db(DB_PATH) as conn:
        conn.execute(
            "UPDATE submissions SET is_active = 0 WHERE team_id = ?",
            (body.team_id,),
        )
        conn.execute(
            """INSERT INTO submissions (id, team_id, code_path, submitted_at, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (submission_id, body.team_id, str(dest_file), timestamp),
        )

    # 7. Enqueue for testing
    queue_pos = enqueue_test(submission_id)

    # Insert test_run row with status=queued
    queued_at = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO test_runs (submission_id, status, queued_at)
               VALUES (?, 'queued', ?)""",
            (submission_id, queued_at),
        )

    return {
        "status":         "queued",
        "version":        timestamp,
        "queue_position": queue_pos,
    }


# ---------------------------------------------------------------------------
# GET /api/teams
# ---------------------------------------------------------------------------

@router.get("/api/teams")
async def list_teams():
    """Return all registered teams (public endpoint)."""
    with get_db(DB_PATH) as conn:
        rows = conn.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
    return [{"id": row["id"], "name": row["name"]} for row in rows]


# ---------------------------------------------------------------------------
# GET /api/test-status/{team_id}
# ---------------------------------------------------------------------------

@router.get("/api/test-status/{team_id}")
async def get_test_status(
    team_id:     str,
    credentials: HTTPBasicCredentials = Depends(_basic_security),
):
    _require_team_auth(team_id, credentials)

    with get_db(DB_PATH) as conn:
        # Latest active submission
        sub_row = conn.execute(
            """SELECT id, submitted_at FROM submissions
               WHERE team_id = ? AND is_active = 1
               ORDER BY submitted_at DESC LIMIT 1""",
            (team_id,),
        ).fetchone()

        if sub_row is None:
            return {
                "team_id":        team_id,
                "latest_version":  None,
                "queue_status":   "no_submission",
                "queue_position": None,
                "report":         None,
            }

        # Latest test run for that submission
        run_row = conn.execute(
            """SELECT * FROM test_runs
               WHERE submission_id = ?
               ORDER BY id DESC LIMIT 1""",
            (sub_row["id"],),
        ).fetchone()

    queue_status   = "no_submission"
    queue_pos_val  = None
    report         = None

    if run_row is None:
        queue_status = "no_submission"
    else:
        status = run_row["status"]
        if status == "queued":
            queue_status  = "waiting"
            queue_pos_val = queue_position(sub_row["id"])
        elif status == "running":
            queue_status  = "running"
        elif status in ("done", "skipped"):
            queue_status = "done"
            report = {
                "laps_completed":   run_row["laps_completed"],
                "best_lap_time":    run_row["best_lap_time"],
                "collisions_minor": run_row["collisions_minor"],
                "collisions_major": run_row["collisions_major"],
                "timeout_warnings": run_row["timeout_warnings"],
                "finish_reason":    run_row["finish_reason"],
                "finished_at":      run_row["finished_at"],
            }

    return {
        "team_id":        team_id,
        "latest_version": sub_row["submitted_at"],
        "queue_status":   queue_status,
        "queue_position": queue_pos_val,
        "report":         report,
    }

"""
Team submission and test-status endpoints.

POST /api/submit                  — upload base64-encoded Python driver (slot_name optional)
POST /api/activate                — switch which slot is the race-active one
GET  /api/test-status/{team_id}   — all 3 slot statuses (Basic Auth)
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

VALID_SLOTS = ("main", "dev", "backup")

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
# ---------------------------------------------------------------------------

_test_queue: list[str] = []
_test_queue_lock = threading.Lock()


def enqueue_test(submission_id: str) -> int:
    with _test_queue_lock:
        _test_queue.append(submission_id)
        return len(_test_queue)


def queue_position(submission_id: str) -> Optional[int]:
    with _test_queue_lock:
        try:
            return _test_queue.index(submission_id) + 1
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

_basic_security = HTTPBasic()


def _require_team_auth(
    team_id: str,
    credentials: HTTPBasicCredentials = Depends(_basic_security),
) -> str:
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
# Request models
# ---------------------------------------------------------------------------

class SubmitRequest(BaseModel):
    team_id:   str
    password:  str
    code:      str        # base64-encoded Python source
    slot_name: str = "main"   # "main" | "dev" | "backup"


class ActivateRequest(BaseModel):
    team_id:   str
    password:  str
    slot_name: str   # which slot to make race-active


# ---------------------------------------------------------------------------
# Shared: validate and save code bytes
# ---------------------------------------------------------------------------

# todo: 与SDK代码审查部分保持一致
def _validate_code(code_str: str) -> None:
    """Run syntax + import + signature checks. Raises HTTPException on failure."""
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
        try:
            result = module.control(dummy_img1, dummy_img2, 0.0)
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


# ---------------------------------------------------------------------------
# POST /api/submit
# ---------------------------------------------------------------------------

@router.post("/api/submit")
async def submit_code(body: SubmitRequest):
    if submissions_locked:
        raise HTTPException(status_code=403, detail="Submissions are locked")

    slot = body.slot_name.lower()
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"slot_name must be one of: {', '.join(VALID_SLOTS)}"
        )

    with get_db(DB_PATH) as conn:
        team_row = conn.execute(
            "SELECT id, name, password_hash FROM teams WHERE id = ?",
            (body.team_id,),
        ).fetchone()

    if team_row is None:
        raise HTTPException(status_code=401, detail="Team not found")
    if not _verify_password(body.password, team_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    try:
        code_bytes = base64.b64decode(body.code)
        code_str   = code_bytes.decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 code: {exc}")

    _validate_code(code_str)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir  = pathlib.Path(SUBMISSIONS_DIR) / body.team_id / slot / timestamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "team_controller.py"
    dest_file.write_text(code_str, encoding="utf-8")

    submission_id = str(uuid.uuid4())

    with get_db(DB_PATH) as conn:
        # Deactivate previous version of the same slot only
        conn.execute(
            "UPDATE submissions SET is_active = 0 WHERE team_id = ? AND slot_name = ?",
            (body.team_id, slot),
        )
        # If this slot was race-active and we're replacing it, keep it race-active
        was_race_active = conn.execute(
            """SELECT COUNT(*) FROM submissions
               WHERE team_id=? AND slot_name=? AND is_race_active=1""",
            (body.team_id, slot),
        ).fetchone()[0]

        conn.execute(
            """INSERT INTO submissions
               (id, team_id, code_path, submitted_at, is_active, slot_name, is_race_active)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (submission_id, body.team_id, str(dest_file), timestamp, slot,
             1 if was_race_active else 0),
        )

        # If no slot is race-active yet, auto-activate main
        any_race_active = conn.execute(
            "SELECT COUNT(*) FROM submissions WHERE team_id=? AND is_race_active=1",
            (body.team_id,),
        ).fetchone()[0]
        if not any_race_active:
            conn.execute(
                "UPDATE submissions SET is_race_active=1 WHERE id=?",
                (submission_id,),
            )

    queue_pos = enqueue_test(submission_id)
    queued_at = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO test_runs (submission_id, status, queued_at) VALUES (?, 'queued', ?)",
            (submission_id, queued_at),
        )

    return {
        "status":         "queued",
        "slot_name":      slot,
        "version":        timestamp,
        "queue_position": queue_pos,
    }


# ---------------------------------------------------------------------------
# POST /api/activate — switch race-active slot
# ---------------------------------------------------------------------------

@router.post("/api/activate")
async def activate_slot(body: ActivateRequest):
    slot = body.slot_name.lower()
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"slot_name must be one of: {', '.join(VALID_SLOTS)}"
        )

    with get_db(DB_PATH) as conn:
        team_row = conn.execute(
            "SELECT id, password_hash FROM teams WHERE id=?", (body.team_id,)
        ).fetchone()
        if team_row is None:
            raise HTTPException(status_code=401, detail="Team not found")
        if not _verify_password(body.password, team_row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid password")

        target = conn.execute(
            """SELECT id FROM submissions
               WHERE team_id=? AND slot_name=? AND is_active=1
               ORDER BY submitted_at DESC LIMIT 1""",
            (body.team_id, slot),
        ).fetchone()
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"槽位 '{slot}' 尚无提交，请先上传代码"
            )

        conn.execute(
            "UPDATE submissions SET is_race_active=0 WHERE team_id=?",
            (body.team_id,),
        )
        conn.execute(
            "UPDATE submissions SET is_race_active=1 WHERE id=?",
            (target["id"],),
        )

    return {"status": "activated", "slot_name": slot, "team_id": body.team_id}


# ---------------------------------------------------------------------------
# GET /api/test-status/{team_id} — all slots
# ---------------------------------------------------------------------------

@router.get("/api/test-status/{team_id}")
async def get_test_status(
    team_id:     str,
    credentials: HTTPBasicCredentials = Depends(_basic_security),
):
    _require_team_auth(team_id, credentials)

    slots_data: dict[str, dict | None] = {}

    with get_db(DB_PATH) as conn:
        for slot in VALID_SLOTS:
            sub = conn.execute(
                """SELECT id, submitted_at, is_race_active FROM submissions
                   WHERE team_id=? AND slot_name=? AND is_active=1
                   ORDER BY submitted_at DESC LIMIT 1""",
                (team_id, slot),
            ).fetchone()

            if sub is None:
                slots_data[slot] = {"version": None, "is_race_active": False, "test": None}
                continue

            run = conn.execute(
                """SELECT * FROM test_runs
                   WHERE submission_id=?
                   ORDER BY id DESC LIMIT 1""",
                (sub["id"],),
            ).fetchone()

            test_info = None
            queue_status = "no_run"
            queue_pos_val = None

            if run:
                status = run["status"]
                if status == "queued":
                    queue_status  = "waiting"
                    queue_pos_val = queue_position(sub["id"])
                elif status == "running":
                    queue_status = "running"
                elif status in ("done", "skipped"):
                    queue_status = "done"
                    test_info = {
                        "laps_completed":   run["laps_completed"],
                        "best_lap_time":    run["best_lap_time"],
                        "collisions_minor": run["collisions_minor"],
                        "collisions_major": run["collisions_major"],
                        "timeout_warnings": run["timeout_warnings"],
                        "finish_reason":    run["finish_reason"],
                        "finished_at":      run["finished_at"],
                    }

            slots_data[slot] = {
                "version":        sub["submitted_at"],
                "is_race_active": bool(sub["is_race_active"]),
                "queue_status":   queue_status,
                "queue_position": queue_pos_val,
                "test":           test_info,
            }

    return {"team_id": team_id, "slots": slots_data}

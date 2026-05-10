"""
Team submission and test-status endpoints.

POST /api/submit                  — upload base64-encoded Python driver (slot_name optional)
POST /api/activate                — switch which slot is the race-active one
POST /api/test-request            — enqueue manual test request for an uploaded slot
GET  /api/test-status/{team_id}   — all 3 slot statuses (Basic Auth)
"""

import asyncio
import base64
import datetime
import os
import pathlib
import tempfile
import threading
from typing import Optional

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from sdk.validate_controller import validate as _sdk_validate
from server.config.config import DB_PATH, SUBMISSIONS_DIR
from server.database.action import (
    create_test_run,
    db_activate_submission_slot,
    db_create_submission_with_slot,
    db_get_submission_by_slot,
    db_get_team_secure,
    get_latest_test_run,
)
from server.database.models import get_db

router = APIRouter()

VALID_SLOTS = ("main", "dev", "backup")

# ---------------------------------------------------------------------------
# Password hashing (direct bcrypt, no passlib)
# ---------------------------------------------------------------------------


def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except:
        return False


# In-memory test queue
# ---------------------------------------------------------------------------

_test_queue: list[dict] = []
_test_queue_lock = threading.Lock()


def enqueue_test(
    submission_id: str, test_run_id: int, slot_name: str, team_id: str
) -> int:
    with _test_queue_lock:
        _test_queue.append(
            {
                "submission_id": submission_id,
                "test_run_id": test_run_id,
                "slot_name": slot_name,
                "team_id": team_id,
            }
        )
        return len(_test_queue)


def dequeue_test() -> Optional[dict]:
    """Pop next test task from the queue. Returns None if empty."""
    with _test_queue_lock:
        return _test_queue.pop(0) if _test_queue else None


def queue_position(submission_id: str) -> Optional[int]:
    with _test_queue_lock:
        for idx, entry in enumerate(_test_queue):
            if entry["submission_id"] == submission_id:
                return idx + 1
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
        row = db_get_team_secure(conn, team_id)

    if row is None:
        raise HTTPException(status_code=401, detail="Team not found")

    if not _verify_password(credentials.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return team_id


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SubmitRequest(BaseModel):
    team_id: str
    password: str
    code: str  # base64-encoded Python source
    slot_name: str = "main"  # "main" | "dev" | "backup"


class ActivateRequest(BaseModel):
    team_id: str
    password: str
    slot_name: str  # which slot to make race-active


class TestRequest(BaseModel):
    team_id: str
    password: str
    slot_name: str  # which slot to request test for


# ---------------------------------------------------------------------------
# Shared: validate and save code bytes
# ---------------------------------------------------------------------------


def _rules_path() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent / "sdk" / "rules.yaml"


def _validate_code(code_str: str) -> list[dict]:
    """
    使用 SDK validate_controller 进行全面的代码审查。

    Returns: warnings 列表（即使通过也可能有 warning）。
    Raises:  HTTPException(400) 如果校验不通过。
    """
    # 去除 BOM 字符（U+FEFF），防止 AST 解析失败
    clean_code = code_str.lstrip("\ufeff")
    with tempfile.NamedTemporaryFile(
        suffix=".py", delete=False, mode="w", encoding="utf-8"
    ) as tmp_src:
        tmp_src.write(clean_code)
        tmp_path = tmp_src.name

    try:
        report = _sdk_validate(
            code_path=tmp_path,
            rules_path=str(_rules_path()),
        )

        if not report.passed:
            detail_lines = [f"代码审查未通过: {report.summary}"]
            for f in report.errors:
                loc = f" (第 {f.lineno} 行)" if f.lineno is not None else ""
                detail_lines.append(f"  [{f.code}]{loc} {f.message}")
            raise HTTPException(
                status_code=400,
                detail="\n".join(detail_lines),
            )

        # 通过后返回 warnings（前端可展示）
        return [f.to_dict() for f in report.warnings]

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
    slot = body.slot_name.lower()
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"slot_name must be one of: {', '.join(VALID_SLOTS)}",
        )

    with get_db(DB_PATH) as conn:
        team_row = db_get_team_secure(conn, body.team_id)

    if team_row is None:
        raise HTTPException(status_code=401, detail="Team not found")
    if not _verify_password(body.password, team_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    # 按赛区检查是否允许提交
    zone_id = team_row["zone_id"]
    if zone_id:
        from server.race.state_machine import RaceState, get_zone_sm

        sm = get_zone_sm(zone_id)
        if sm.state != RaceState.REGISTRATION:
            raise HTTPException(
                status_code=403,
                detail=f"赛区 '{zone_id}' 的代码提交已关闭（当前状态: {sm.state.value}），不再接受新的提交。",
            )

    try:
        code_bytes = base64.b64decode(body.code)
        code_str = code_bytes.decode("utf-8")
        # 去除 BOM 字符（U+FEFF），防止后续解析和运行失败
        code_str = code_str.lstrip("\ufeff")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 code: {exc}")

    warnings = _validate_code(code_str)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = pathlib.Path(SUBMISSIONS_DIR) / body.team_id / slot / timestamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "team_controller.py"
    dest_file.write_text(code_str, encoding="utf-8")

    with get_db(DB_PATH) as conn:
        submission_id = db_create_submission_with_slot(
            conn,
            body.team_id,
            str(dest_file),
            slot,
            submitted_at=timestamp,
        )

    return {
        "status": "uploaded",
        "slot_name": slot,
        "version": timestamp,
        "warnings": warnings,
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
            detail=f"slot_name must be one of: {', '.join(VALID_SLOTS)}",
        )

    with get_db(DB_PATH) as conn:
        team_row = db_get_team_secure(conn, body.team_id)
        if team_row is None:
            raise HTTPException(status_code=401, detail="Team not found")
        if not _verify_password(body.password, team_row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid password")

        success = db_activate_submission_slot(conn, body.team_id, slot)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"槽位 '{slot}' 尚无提交，请先上传代码"
            )

    return {"status": "activated", "slot_name": slot, "team_id": body.team_id}


@router.post("/api/test-request")
async def request_test(body: TestRequest):
    slot = body.slot_name.lower()
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"slot_name must be one of: {', '.join(VALID_SLOTS)}",
        )

    # 赛程已开始则拒绝测试
    from server.race.state_machine import all_running_zones

    running = all_running_zones()
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"赛程已在进行中 ({len(running)} 个赛区)，无法提交测试申请",
        )

    with get_db(DB_PATH) as conn:
        team_row = db_get_team_secure(conn, body.team_id)

    if team_row is None:
        raise HTTPException(status_code=401, detail="Team not found")
    if not _verify_password(body.password, team_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    with get_db(DB_PATH) as conn:
        submission = db_get_submission_by_slot(conn, body.team_id, slot)

        if submission is None:
            raise HTTPException(
                status_code=404,
                detail=f"槽位 '{slot}' 尚无提交，请先上传代码",
            )

        last_run = get_latest_test_run(conn, submission["id"])

        if last_run and last_run["status"] in ("queued", "running"):
            queue_pos = queue_position(submission["id"])
            raise HTTPException(
                status_code=409,
                detail=(
                    f"测试已在队列中，当前位置 {queue_pos}"
                    if queue_pos is not None
                    else "测试已在队列中"
                ),
            )

        queued_at = datetime.datetime.now().isoformat()
        test_run_id = create_test_run(conn, submission["id"], queued_at)
        queue_pos = enqueue_test(submission["id"], test_run_id, slot, body.team_id)

    return {
        "status": "queued",
        "slot_name": slot,
        "version": submission["submitted_at"],
        "queue_position": queue_pos,
    }


# ---------------------------------------------------------------------------
# GET /api/test-status/{team_id} — all slots
# ---------------------------------------------------------------------------


@router.get("/api/test-status/{team_id}")
async def get_test_status(
    team_id: str,
    credentials: HTTPBasicCredentials = Depends(_basic_security),
):
    _require_team_auth(team_id, credentials)

    slots_data: dict[str, dict | None] = {}

    with get_db(DB_PATH) as conn:
        for slot in VALID_SLOTS:
            sub = db_get_submission_by_slot(conn, team_id, slot)

            if sub is None:
                slots_data[slot] = {
                    "version": None,
                    "is_race_active": False,
                    "test": None,
                }
                continue

            run = get_latest_test_run(conn, sub["id"])

            test_info = None
            queue_status = "no_run"
            queue_pos_val = None

            if run:
                status = run["status"]
                if status == "queued":
                    queue_status = "waiting"
                    queue_pos_val = queue_position(sub["id"])
                elif status == "running":
                    queue_status = "running"
                elif status in ("done", "skipped"):
                    queue_status = "done"
                    test_info = {
                        "laps_completed": run["laps_completed"],
                        "best_lap_time": run["best_lap_time"],
                        "collisions_minor": run["collisions_minor"],
                        "collisions_major": run["collisions_major"],
                        "timeout_warnings": run["timeout_warnings"],
                        "finish_reason": run["finish_reason"],
                        "finished_at": run["finished_at"],
                    }

            slots_data[slot] = {
                "version": sub["submitted_at"],
                "is_race_active": bool(sub["is_race_active"]),
                "queue_status": queue_status,
                "queue_position": queue_pos_val,
                "test": test_info,
            }

    return {"team_id": team_id, "slots": slots_data}

"""
Admin REST endpoints.

All routes require HTTP Basic Auth (password == ADMIN_PASSWORD).

Prefix: /api/admin
"""

import asyncio
import base64
import datetime
import json
import pathlib
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from server.config.config import ADMIN_PASSWORD, DB_PATH, RECORDINGS_DIR, SUBMISSIONS_DIR
from server.database.models import get_db
from server.race.state_machine import RaceState, state_machine
from server.utils.simnode_client import (
    start_race as simnode_start_race,
    cancel_race as simnode_cancel_race,
    get_race_status as simnode_get_status,
    get_race_result as simnode_get_result,
    list_races as simnode_list_races,
)

router = APIRouter(prefix="/api/admin")
_security = HTTPBasic()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    ok = secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SetSessionBody(BaseModel):
    session_type: str
    session_id:   str
    team_ids:     list[str]
    total_laps:   int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _running_state_for(session_type: str) -> RaceState:
    mapping = {
        "qualifying":  RaceState.QUALIFYING_RUNNING,
        "group_race":  RaceState.GROUP_RACE_RUNNING,
        "semi":        RaceState.SEMI_RUNNING,
        "final":       RaceState.FINAL_RUNNING,
    }
    state = mapping.get(session_type.lower())
    if state is None:
        raise HTTPException(status_code=400, detail=f"Unknown session_type '{session_type}'")
    return state


def _finished_state_for(session_type: str) -> RaceState:
    return {
        "qualifying": RaceState.QUALIFYING_FINISHED,
        "group_race": RaceState.GROUP_RACE_FINISHED,
        "semi":       RaceState.SEMI_FINISHED,
        "final":      RaceState.FINAL_FINISHED,
    }.get(session_type.lower(), RaceState.IDLE)


def _aborted_state_for(session_type: str) -> RaceState:
    return {
        "qualifying": RaceState.QUALIFYING_ABORTED,
        "group_race": RaceState.GROUP_RACE_ABORTED,
        "semi":       RaceState.SEMI_ABORTED,
        "final":      RaceState.IDLE,
    }.get(session_type.lower(), RaceState.IDLE)


def _rank_to_points(rank: Optional[int]) -> int:
    return {1: 10, 2: 7, 3: 5, 4: 3}.get(rank, 1)


async def _broadcast(state: str, session_id: Optional[str] = None, pid: Optional[int] = None, recording_path: Optional[str] = None):
    from server.ws.admin import broadcast_state
    await broadcast_state(state, session_id=session_id, webots_pid=pid, recording_path=recording_path)


# ---------------------------------------------------------------------------
# POST /api/admin/lock-submissions
# ---------------------------------------------------------------------------

@router.post("/lock-submissions")
async def lock_submissions(_auth=Depends(require_admin)):
    from server.blueprints.submission import submissions_locked as _fake  # noqa
    import server.blueprints.submission as sub_module
    sub_module.submissions_locked = True
    return {"status": "locked"}


# ---------------------------------------------------------------------------
# POST /api/admin/set-session
# ---------------------------------------------------------------------------

@router.post("/set-session")
async def set_session(body: SetSessionBody, _auth=Depends(require_admin)):
    """Store session config in DB; resolve Base64 car codes from submissions."""
    target_running = _running_state_for(body.session_type)

    # Build cars list: read code file and encode to Base64
    cars = []
    with get_db(DB_PATH) as conn:
        for idx, team_id in enumerate(body.team_ids):
            team_row = conn.execute(
                "SELECT id, name FROM teams WHERE id = ?", (team_id,)
            ).fetchone()
            if team_row is None:
                raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

            sub_row = conn.execute(
                """SELECT code_path FROM submissions
                   WHERE team_id = ? AND is_active = 1
                   ORDER BY submitted_at DESC LIMIT 1""",
                (team_id,),
            ).fetchone()

            if sub_row and pathlib.Path(sub_row["code_path"]).exists():
                code_bytes = pathlib.Path(sub_row["code_path"]).read_bytes()
                code_b64 = base64.b64encode(code_bytes).decode()
            else:
                # Use straight template if no submission
                template = pathlib.Path(__file__).resolve().parent.parent.parent / "sdk" / "team_controller.py"
                code_b64 = base64.b64encode(template.read_bytes()).decode() if template.exists() else ""

            cars.append({
                "car_slot":  f"car_{idx + 1}",
                "team_id":   team_id,
                "team_name": team_row["name"],
                "code_b64":  code_b64,
            })

    # Persist session record
    with get_db(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO race_sessions
               (id, type, team_ids, total_laps, started_at, finished_at, phase, result)
               VALUES (?, ?, ?, ?, NULL, NULL, 'waiting', NULL)
               ON CONFLICT(id) DO UPDATE SET
                 type=excluded.type, team_ids=excluded.team_ids,
                 total_laps=excluded.total_laps, phase='waiting',
                 started_at=NULL, finished_at=NULL, result=NULL""",
            (body.session_id, body.session_type, json.dumps(body.team_ids), body.total_laps),
        )

    # Cache cars in memory for start-race (keyed by session_id)
    _pending_cars[body.session_id] = cars
    return {"status": "ready", "session_id": body.session_id}


# In-memory store: session_id → cars list (valid until start-race consumes it)
_pending_cars: dict[str, list] = {}


# ---------------------------------------------------------------------------
# POST /api/admin/start-race
# ---------------------------------------------------------------------------

@router.post("/start-race")
async def start_race(_auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, type, total_laps FROM race_sessions WHERE phase = 'waiting' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=409, detail="No session in 'waiting' phase. Call set-session first.")

    session_id   = row["id"]
    session_type = row["type"]
    total_laps   = row["total_laps"]
    target_state = _running_state_for(session_type)

    try:
        state_machine.transition(target_state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    cars = _pending_cars.pop(session_id, [])
    if not cars:
        raise HTTPException(status_code=409, detail="Car codes missing. Call set-session again.")

    try:
        resp = await asyncio.to_thread(
            simnode_start_race, session_id, session_type, total_laps, cars
        )
    except RuntimeError as exc:
        state_machine.reset()
        raise HTTPException(status_code=503, detail=f"Sim Node unreachable: {exc}")

    now = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        conn.execute(
            "UPDATE race_sessions SET phase='running', started_at=? WHERE id=?",
            (now, session_id),
        )

    # Monitor Sim Node for completion in background
    asyncio.create_task(_watch_simnode(session_id, session_type))

    await _broadcast("running", session_id=session_id)
    return {"status": "running", "session_id": session_id, "stream_url": resp.get("stream_ws_url")}


async def _watch_simnode(session_id: str, session_type: str):
    """Poll Sim Node status every 5s until race ends."""
    none_strikes = 0
    while True:
        await asyncio.sleep(5)
        status = await asyncio.to_thread(simnode_get_status, session_id)
        if status is None:
            none_strikes += 1
            if none_strikes >= 3:   # 3 consecutive unreachable → give up
                break
            continue
        none_strikes = 0
        if status == "completed":
            await _handle_finished(session_id, session_type)
            break
        if status in ("error", "cancelled"):
            await _handle_aborted(session_id, session_type)
            break


async def _handle_finished(session_id: str, session_type: str):
    try:
        state_machine.transition(_finished_state_for(session_type))
    except ValueError:
        pass

    # Ensure metadata.json exists so the recording endpoint returns 200
    rec_dir = pathlib.Path(RECORDINGS_DIR) / session_id
    meta_file = rec_dir / "metadata.json"
    recording_path = str(rec_dir.resolve())

    if not meta_file.exists():
        result = await asyncio.to_thread(simnode_get_result, session_id) or {}
        result.setdefault("session_id", session_id)
        result.setdefault("session_type", session_type)
        result.setdefault("recording_path", recording_path)
        result.setdefault("recorded_at", datetime.datetime.now().isoformat())
        rec_dir.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    now = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        conn.execute(
            "UPDATE race_sessions SET phase='recording_ready', finished_at=? WHERE id=?",
            (now, session_id),
        )
    await _broadcast("recording_ready", session_id=session_id, recording_path=recording_path)


async def _handle_aborted(session_id: str, session_type: str):
    try:
        state_machine.transition(_aborted_state_for(session_type))
    except ValueError:
        pass
    now = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        conn.execute(
            "UPDATE race_sessions SET phase='aborted', finished_at=? WHERE id=?",
            (now, session_id),
        )
    await _broadcast("aborted", session_id=session_id)


# ---------------------------------------------------------------------------
# POST /api/admin/stop-race
# ---------------------------------------------------------------------------

@router.post("/stop-race")
async def stop_race(_auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, type FROM race_sessions WHERE phase='running' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    session_id   = row["id"] if row else None
    session_type = row["type"] if row else "qualifying"

    if session_id:
        await asyncio.to_thread(simnode_cancel_race, session_id)
        # Graceful stop writes metadata.json; check outcome to route correctly
        status = await asyncio.to_thread(simnode_get_status, session_id)
        if status == "completed":
            await _handle_finished(session_id, session_type)
        else:
            await _handle_aborted(session_id, session_type)

    return {"status": "stopping"}


# ---------------------------------------------------------------------------
# POST /api/admin/reset-track
# ---------------------------------------------------------------------------

@router.post("/reset-track")
async def reset_track(_auth=Depends(require_admin)):
    state_machine.reset()
    await _broadcast("idle")
    return {"status": "idle"}


# ---------------------------------------------------------------------------
# GET /api/admin/standings
# ---------------------------------------------------------------------------

@router.get("/standings")
async def get_standings(_auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT rp.team_id, t.name, SUM(rp.points) as total_points
               FROM race_points rp JOIN teams t ON rp.team_id = t.id
               GROUP BY rp.team_id ORDER BY total_points DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Phase finalization
# ---------------------------------------------------------------------------

@router.post("/finalize-qualifying")
async def finalize_qualifying(_auth=Depends(require_admin)):
    try:
        state_machine.transition(RaceState.QUALIFYING_DONE)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle")
    return {"state": state_machine.state}


@router.post("/finalize-group")
async def finalize_group(_auth=Depends(require_admin)):
    try:
        state_machine.transition(RaceState.GROUP_DONE)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle")
    return {"state": state_machine.state}


@router.post("/finalize-semi")
async def finalize_semi(_auth=Depends(require_admin)):
    try:
        state_machine.transition(RaceState.SEMI_DONE)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle")
    return {"state": state_machine.state}


@router.post("/close-event")
async def close_event(_auth=Depends(require_admin)):
    try:
        state_machine.transition(RaceState.CLOSED)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle")
    return {"state": state_machine.state}


# ---------------------------------------------------------------------------
# GET /api/admin/live-frame/{session_id}  — proxy overhead camera JPEG from simnode
# ---------------------------------------------------------------------------

from server.utils.simnode_client import SIMNODE_URL as _SIMNODE_URL


@router.get("/live-frame/{session_id}")
async def get_live_frame(session_id: str, _auth=Depends(require_admin)):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_SIMNODE_URL}/race/{session_id}/frame",
                timeout=3.0,
            )
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="No frame available yet")
        resp.raise_for_status()
        return Response(
            content=resp.content,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Simnode unreachable")

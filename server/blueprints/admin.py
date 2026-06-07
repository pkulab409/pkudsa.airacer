"""
Admin REST endpoints.

All routes require HTTP Basic Auth (password == ADMIN_PASSWORD).

Prefix: /api/admin

Zone-scoped race control:
  POST /api/admin/zones/{zone_id}/set-session
  POST /api/admin/zones/{zone_id}/start-race
  POST /api/admin/zones/{zone_id}/stop-race
  POST /api/admin/zones/{zone_id}/finalize
  GET  /api/admin/zones/{zone_id}/standings
  GET  /api/admin/zones/{zone_id}/bracket

Zone CRUD:
  GET    /api/admin/zones
  POST   /api/admin/zones
  DELETE /api/admin/zones/{zone_id}
  GET    /api/admin/zones/{zone_id}/teams

Legacy (default zone) endpoints kept for backward compatibility.
"""

import asyncio
import base64
import datetime
import json
import pathlib
import secrets
import sqlite3
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from server.config.config import (
    ADMIN_PASSWORD,
    DB_PATH,
    RECORDINGS_DIR,
    SUBMISSIONS_DIR,
)
from server.database.action import (
    create_race as db_create_race,
)
from server.database.action import (
    db_create_zone,
    db_delete_team,
    db_delete_zone,
    db_ensure_default_zone,
    db_get_placement_rankings,
    db_get_running_session,
    db_get_stage_session_results,
    db_get_teams_with_code,
    db_get_waiting_session,
    db_get_zone,
    db_get_zone_standings,
    db_get_zone_team_count,
    db_get_zone_team_ids,
    db_get_zone_teams,
    db_list_zones,
    db_mark_session_aborted,
    db_mark_session_finished,
    db_mark_session_running,
    db_upsert_session,
)
from server.database.models import get_db
from server.race.bracket import compute_bracket
from server.race.grouping import (
    select_group_stage_advancers,
    select_placement_advancers,
    select_semi_finalists,
    snake_draft_group,
)
from server.race.state_machine import (
    RaceState,
    get_zone_sm,
    remove_zone_sm,
)
from server.utils.simnode_client import (
    SIMNODE_URL as _SIMNODE_URL,
)
from server.utils.simnode_client import (
    cancel_race as simnode_cancel_race,
)
from server.utils.simnode_client import (
    get_race_frame_async as _get_race_frame_async,  # 复用共享连接池
)
from server.utils.simnode_client import (
    get_race_result as simnode_get_result,
)
from server.utils.simnode_client import (
    get_race_status as simnode_get_status,
)
from server.utils.simnode_client import (
    list_races as simnode_list_races,
)
from server.utils.simnode_client import (
    start_race as simnode_start_race,
)

# ---------------------------------------------------------------------------
# Admin impersonate token (in-memory, 5-min TTL)
# ---------------------------------------------------------------------------

_impersonate_tokens: dict[str, dict] = {}  # token → {team_id, expires_at}


def _cleanup_expired_tokens():
    now = time.time()
    expired = [k for k, v in _impersonate_tokens.items() if v["expires_at"] < now]
    for k in expired:
        del _impersonate_tokens[k]


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


class ZoneCreateBody(BaseModel):
    id: str
    name: str
    description: str = ""
    total_laps: int = 3


class SetSessionBody(BaseModel):
    session_type: str
    session_id: str
    team_ids: list[str]
    total_laps: int


class ZoneSetSessionBody(BaseModel):
    session_type: str
    session_id: str
    team_ids: Optional[list[str]] = None  # if None, auto-select from zone
    total_laps: Optional[int] = None  # if None, use zone default
    name: Optional[str] = None  # 可读名称


class ZoneCreateRaceBody(BaseModel):
    session_type: str  # placement / group_stage / semi / final
    team_ids: list[str]
    total_laps: int
    name: Optional[str] = None


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _running_state_for(session_type: str) -> RaceState:
    mapping = {
        "placement": RaceState.PLACEMENT_RUNNING,
        "group_stage": RaceState.GROUP_STAGE_RUNNING,
        "semi": RaceState.SEMI_RUNNING,
        "final": RaceState.FINAL_RUNNING,
    }
    state = mapping.get(session_type.lower())
    if state is None:
        raise HTTPException(
            status_code=400, detail=f"Unknown session_type '{session_type}'"
        )
    return state


def _finished_state_for(session_type: str) -> RaceState:
    return {
        "placement": RaceState.PLACEMENT_FINISHED,
        "group_stage": RaceState.GROUP_STAGE_FINISHED,
        "semi": RaceState.SEMI_FINISHED,
        "final": RaceState.FINAL_FINISHED,
    }.get(session_type.lower(), RaceState.IDLE)


def _aborted_state_for(session_type: str) -> RaceState:
    return {
        "placement": RaceState.PLACEMENT_ABORTED,
        "group_stage": RaceState.GROUP_STAGE_ABORTED,
        "semi": RaceState.SEMI_ABORTED,
        "final": RaceState.IDLE,
    }.get(session_type.lower(), RaceState.IDLE)


def _determine_current_stage(conn, zone_id: str, bracket: dict) -> Optional[str]:
    """Find the first stage that has unfinished sessions; None if all done."""
    for stage in bracket["stages"]:
        finished = conn.execute(
            "SELECT COUNT(*) FROM race_sessions "
            "WHERE zone_id=? AND type=? AND phase IN ('recording_ready','finished')",
            (zone_id, stage),
        ).fetchone()[0]
        if finished < bracket["sessions_per_stage"][stage]:
            return stage
    return None


def _pre_create_stage_sessions(conn, zone_id: str, stage: str, bracket: dict) -> str:
    """Pre-create ALL sessions for a stage at once. Returns the first session_id."""
    cars_per = bracket["cars_per_session"][stage]
    total_sessions = bracket["sessions_per_stage"][stage]
    laps = bracket["laps_per_stage"][stage]
    all_teams = db_get_zone_team_ids(conn, zone_id)

    all_teams_list: list[list[str]] = []

    if stage == "qualification":
        # 资格赛：每队单独 1 场
        all_teams_list = [[tid] for tid in all_teams]
    elif stage == "placement":
        # 排位赛：按资格赛成绩蛇形分 4 批，每批 6 车
        ranked = _get_qualification_rankings(conn, zone_id, all_teams)
        all_teams_list = snake_draft_group(ranked, total_sessions)
    elif stage == "group_stage":
        # 分组赛：按排位赛成绩蛇形分 2 组
        ranked = db_get_placement_rankings(conn, zone_id)
        ranked_ids = [r["team_id"] for r in ranked] if ranked else all_teams
        all_teams_list = snake_draft_group(ranked_ids, total_sessions)
    elif stage == "semi":
        # 半决赛：分组赛每组前 4 晋级后均分到 2 场
        prev = db_get_stage_session_results(conn, zone_id, "group_stage")
        advancers = select_group_stage_advancers(prev)
        all_teams_list = [
            advancers[i * cars_per : (i + 1) * cars_per] for i in range(total_sessions)
        ]
    elif stage == "final":
        # 决赛：半决赛每场前 2 晋级
        prev = db_get_stage_session_results(conn, zone_id, "semi")
        advancers = select_semi_finalists(prev)
        all_teams_list = [advancers[:cars_per]]
    else:
        all_teams_list = [all_teams[:cars_per]]

    # 清理同 zone+stage 的旧 waiting 场次 + 已取消的旧记录，避免累积
    conn.execute(
        "DELETE FROM race_sessions WHERE zone_id=? AND type=? AND phase IN ('waiting', 'cancelled')",
        (zone_id, stage),
    )

    ts = int(datetime.datetime.now().timestamp())
    first_sid = None

    # 可读阶段名前缀
    stage_prefix = {
        "qualification": "资格赛",
        "placement": "排位赛",
        "group_stage": "小组赛",
        "semi": "半决赛",
        "final": "决赛",
    }
    prefix = stage_prefix.get(stage, stage)

    for i, team_ids in enumerate(all_teams_list):
        if not team_ids:
            continue
        sid = f"{zone_id}_{stage}_{i + 1}_{ts}"
        name = f"{prefix} 第{i + 1}场" if total_sessions > 1 else prefix
        db_upsert_session(conn, sid, stage, team_ids, laps, zone_id, name=name)
        if first_sid is None:
            first_sid = sid
    return first_sid


def _rank_to_points(rank: Optional[int]) -> int:
    return {1: 10, 2: 7, 3: 5, 4: 3}.get(rank, 1)


async def _broadcast(
    state: str,
    zone_id: str = "default",
    session_id: Optional[str] = None,
    session_type: Optional[str] = None,
    pid: Optional[int] = None,
    recording_path: Optional[str] = None,
):
    from server.ws.admin import broadcast_state

    await broadcast_state(
        state,
        zone_id=zone_id,
        session_id=session_id,
        session_type=session_type,
        webots_pid=pid,
        recording_path=recording_path,
    )


def _build_cars(teams_data: list) -> list:
    """Pure file I/O: read each team's code file and base64-encode it.

    When a team has no submitted code (code_path is empty/missing),
    sends empty code so the car stays stationary.
    """
    cars = []
    for idx, t in enumerate(teams_data):
        code_path = t.get("code_path")
        if code_path and pathlib.Path(code_path).exists():
            code_b64 = base64.b64encode(pathlib.Path(code_path).read_bytes()).decode()
        else:
            code_b64 = ""  # 队伍未提交代码，小车静止不动
        cars.append(
            {
                "car_slot": f"car_{idx + 1}",
                "team_id": t["id"],
                "team_name": t["name"],
                "code_b64": code_b64,
            }
        )
    return cars


# Track current running session per zone
_zone_running_session: dict[str, str] = {}


def _get_running_session_id(zone_id: str) -> Optional[str]:
    sid = _zone_running_session.get(zone_id)
    if sid:
        return sid
    # Fallback after a server restart: read running_session from the database
    try:
        with get_db(DB_PATH) as conn:
            row = db_get_running_session(conn, zone_id)
        if row:
            sid = row["id"]
            _zone_running_session[zone_id] = sid  # repopulate in-memory cache
            return sid
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Zone CRUD
# ---------------------------------------------------------------------------


@router.get("/zones")
async def list_zones(_auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        rows = db_list_zones(conn)
    result = []
    for r in rows:
        sm = get_zone_sm(r["id"])
        result.append(
            {
                "zone_id": r["id"],
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "total_laps": r["total_laps"],
                "created_at": r["created_at"],
                "team_count": r["team_count"],
                "state": sm.state.value,
                "registration_open": bool(r.get("registration_open", 1)),
                "running_session": _zone_running_session.get(r["id"]),
            }
        )
    return result


@router.post("/zones")
async def create_zone(body: ZoneCreateBody, _auth=Depends(require_admin)):
    import re

    if not re.match(r"^[a-zA-Z0-9_-]{2,32}$", body.id):
        raise HTTPException(
            status_code=400, detail="Zone ID: 字母/数字/下划线/连字符，2-32字符"
        )
    now = datetime.datetime.now().isoformat()
    try:
        with get_db(DB_PATH) as conn:
            db_create_zone(
                conn, body.id, body.name, body.description, body.total_laps, now
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"赛区ID已存在: {body.id}")
    return {"status": "created", "zone_id": body.id}


@router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: str, _auth=Depends(require_admin)):
    sm = get_zone_sm(zone_id)
    if sm.is_running():
        raise HTTPException(status_code=409, detail="赛区有比赛正在进行，无法删除")
    with get_db(DB_PATH) as conn:
        if not db_delete_zone(conn, zone_id):
            raise HTTPException(status_code=404, detail=f"赛区未找到: {zone_id}")
    remove_zone_sm(zone_id)
    return {"status": "deleted", "zone_id": zone_id}


@router.get("/zones/{zone_id}/teams")
async def get_zone_teams(zone_id: str, _auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        return db_get_zone_teams(conn, zone_id)


@router.get("/zones/{zone_id}/standings")
async def get_zone_standings(zone_id: str, _auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        return db_get_zone_standings(conn, zone_id)


@router.get("/zones/{zone_id}/bracket")
async def get_zone_bracket(zone_id: str, _auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        count = db_get_zone_team_count(conn, zone_id)
    return compute_bracket(count)


@router.get("/zones/{zone_id}/pending-session")
async def get_pending_session(zone_id: str, _auth=Depends(require_admin)):
    with get_db(DB_PATH) as conn:
        row = db_get_waiting_session(conn, zone_id)
    if row is None:
        return {"zone_id": zone_id, "session": None}
    row_dict = dict(row)
    return {
        "zone_id": zone_id,
        "session": {
            "id": row_dict["id"],
            "type": row_dict["type"],
            "total_laps": row_dict["total_laps"],
            "team_count": len(row_dict["team_ids"]),
            "team_ids": row_dict["team_ids"],
            "name": row_dict.get("name"),
        },
    }


# ---------------------------------------------------------------------------
# Race history & prepare
# ---------------------------------------------------------------------------


@router.get("/zones/{zone_id}/race-history")
async def get_race_history(zone_id: str, _auth=Depends(require_admin)):
    """获取赛区已完成的正赛历史。"""
    from server.database.action import db_get_race_history

    with get_db(DB_PATH) as conn:
        history = db_get_race_history(conn, zone_id)
    return {"zone_id": zone_id, "history": history}


@router.get("/zones/{zone_id}/prepared-races")
async def get_prepared_races(zone_id: str, _auth=Depends(require_admin)):
    """获取赛区待执行的 race_prepare 记录。"""
    from server.database.action import db_get_zone_prepared_races

    with get_db(DB_PATH) as conn:
        prepared = db_get_zone_prepared_races(conn, zone_id)
    return {"zone_id": zone_id, "prepared": prepared}


@router.post("/zones/{zone_id}/generate-stage/{stage_name}")
async def generate_stage(
    zone_id: str,
    stage_name: str,
    body: dict = {},
    request: Request = None,
    _auth=Depends(require_admin),
):
    from fastapi import Request as _Request

    body_dict = body if isinstance(body, dict) else {}

    """
    生成某个阶段的比赛计划写入 race_prepare 表。
    placement 需要 body.eliminate_team_id 指定淘汰队伍。
    """
    from server.database.action import (
        db_clear_prepared_races,
        db_create_prepared_race,
        db_get_race_history,
    )

    stage_prefix = {
        "qualification": "资格赛",
        "placement": "排位赛",
        "group_stage": "小组赛",
        "semi": "半决赛",
        "final": "决赛",
    }

    if stage_name not in stage_prefix:
        raise HTTPException(
            status_code=400,
            detail=f"无效阶段: {stage_name}",
        )

    with get_db(DB_PATH) as conn:
        team_count = db_get_zone_team_count(conn, zone_id)
        bracket = compute_bracket(team_count)
        all_teams = db_get_zone_team_ids(conn, zone_id)

        # ── 阶段条件检查 ─────────────────────────
        if stage_name == "qualification":
            # 资格赛：不能有已完成的正赛
            history = db_get_race_history(conn, zone_id, limit=1)
            if history:
                raise HTTPException(
                    status_code=409,
                    detail="已有正赛记录，请先重置赛区",
                )

        elif stage_name == "placement":
            _check_stage_done(conn, zone_id, "qualification", bracket, "资格赛")
            eliminate_team = body_dict.get("eliminate_team_id", "")
            if not eliminate_team:
                raise HTTPException(
                    status_code=409,
                    detail="need_elimination",
                    headers={"X-Need-Elimination": "true"},
                )
            if eliminate_team not in all_teams:
                raise HTTPException(
                    status_code=400, detail=f"队伍 {eliminate_team} 不在本赛区"
                )
            all_teams = [t for t in all_teams if t != eliminate_team]
            bracket = compute_bracket(len(all_teams))  # 重新计算 24 队 bracket

        elif stage_name == "group_stage":
            _check_stage_done(conn, zone_id, "placement", bracket, "排位赛")

        elif stage_name == "semi":
            _check_stage_done(conn, zone_id, "group_stage", bracket, "分组赛")

        elif stage_name == "final":
            _check_stage_done(conn, zone_id, "semi", bracket, "半决赛")

        # ── 清除旧计划 + 生成新计划 ─────────────
        db_clear_prepared_races(conn, zone_id, stage_name)

        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sessions = _build_stage_sessions(conn, zone_id, stage_name, bracket, all_teams)

        pfx = stage_prefix[stage_name]
        created = 0
        for i, s in enumerate(sessions):
            race_id = str(uuid.uuid4())
            sname = f"{pfx} 第{i + 1}场" if len(sessions) > 1 else pfx
            db_create_prepared_race(
                conn,
                race_id=race_id,
                race_type=stage_name,
                zone_id=zone_id,
                participant_ids=s["team_ids"],
                total_laps=s["total_laps"],
                name=sname,
                created_at=ts,
            )
            created += 1

    return {
        "status": "generated",
        "stage": stage_name,
        "stage_name": pfx,
        "count": created,
    }


@router.post("/zones/{zone_id}/execute-prepared-race/{race_id}")
async def execute_prepared_race(
    zone_id: str,
    race_id: str,
    _auth=Depends(require_admin),
):
    """将 race_prepare 中的记录转为实际比赛（写入 races + race_sessions 并入队）。"""
    from server.blueprints.races import _enqueue_race
    from server.database.action import (
        db_get_zone_prepared_races,
        db_update_prepared_race,
    )

    with get_db(DB_PATH) as conn:
        prepared = db_get_zone_prepared_races(conn, zone_id)
        target = None
        for p in prepared:
            if p["id"] == race_id:
                target = p
                break

    if target is None:
        raise HTTPException(status_code=404, detail="未找到该比赛计划")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db(DB_PATH) as conn:
        db_create_race(
            conn,
            race_id=race_id,
            race_type=target["type"],
            zone_id=zone_id,
            initiator=None,
            participant_ids=target["participant_ids"],
            world_key=target.get("world_key", "complex"),
            total_laps=target["total_laps"],
            name=target["name"],
            created_at=now,
        )

        db_upsert_session(
            conn,
            race_id,
            target["type"],
            target["participant_ids"],
            target["total_laps"],
            zone_id,
            name=target["name"],
        )

        db_update_prepared_race(conn, race_id, status="executed")

    _enqueue_race(race_id)

    return {
        "status": "executed",
        "race_id": race_id,
        "name": target["name"],
    }


def _get_qualification_rankings(conn, zone_id: str, team_ids: list[str]) -> list[str]:
    """从资格赛成绩获取排序（best_lap_time 升序），只返回 team_ids 中的队伍。"""
    results = db_get_stage_session_results(conn, zone_id, "qualification")
    timed: list[tuple[str, float]] = []
    seen: set[str] = set()
    for sr in results:
        for entry in sr.get("rankings", []):
            tid = entry.get("team_id")
            if not tid or tid in seen or tid not in team_ids:
                continue
            bt = entry.get("best_lap_time")
            if bt is not None:
                seen.add(tid)
                timed.append((tid, bt))
    timed.sort(key=lambda x: x[1])
    # 没有成绩的排在末尾
    ranked = [t for t, _ in timed]
    for tid in team_ids:
        if tid not in seen:
            ranked.append(tid)
    return ranked


def _check_stage_done(
    conn, zone_id: str, stage: str, bracket: dict, stage_name: str
) -> None:
    total = bracket["sessions_per_stage"].get(stage, 0)
    finished = conn.execute(
        "SELECT COUNT(*) FROM race_sessions WHERE zone_id=? AND type=? AND phase IN ('recording_ready','finished')",
        (zone_id, stage),
    ).fetchone()[0]
    if finished < total:
        raise HTTPException(
            status_code=409,
            detail=f"{stage_name}未完成（{finished}/{total}），无法生成下一阶段",
        )


def _build_stage_sessions(
    conn, zone_id: str, stage: str, bracket: dict, all_teams: list[str]
) -> list[dict]:
    """计算某阶段的场次数据（不写 DB），返回 [{team_ids, total_laps}, ...]"""
    cars_per = bracket["cars_per_session"][stage]
    total_sessions = bracket["sessions_per_stage"][stage]
    laps = bracket["laps_per_stage"][stage]
    sessions: list[dict] = []

    if stage == "qualification":
        for tid in all_teams:
            sessions.append({"team_ids": [tid], "total_laps": laps})

    elif stage == "placement":
        # 排位赛：按资格赛成绩蛇形分 4 批，每批 6 车
        ranked = _get_qualification_rankings(conn, zone_id, all_teams)
        groups = snake_draft_group(ranked, total_sessions)
        for g in groups:
            sessions.append({"team_ids": g, "total_laps": laps})

    elif stage == "group_stage":
        # 排位赛取前 12 名，蛇形分 2 组
        ranked = db_get_placement_rankings(conn, zone_id)
        top_n = bracket["advancement"].get("placement", 12)
        advancer_ids = (
            select_placement_advancers(
                [
                    {
                        "rankings": [
                            {
                                "team_id": r["team_id"],
                                "best_lap_time": r["best_lap_time"],
                            }
                            for r in ranked
                        ]
                    }
                ],
                top_n=top_n,
            )
            if ranked
            else all_teams[:top_n]
        )
        groups = snake_draft_group(advancer_ids, total_sessions)
        for g in groups:
            sessions.append({"team_ids": g, "total_laps": laps})

    elif stage == "semi":
        prev = db_get_stage_session_results(conn, zone_id, "group_stage")
        advancers = select_group_stage_advancers(prev)
        for i in range(total_sessions):
            chunk = advancers[i * cars_per : (i + 1) * cars_per]
            sessions.append({"team_ids": chunk, "total_laps": laps})

    elif stage == "final":
        prev = db_get_stage_session_results(conn, zone_id, "semi")
        advancers = select_semi_finalists(prev)
        sessions.append({"team_ids": advancers[:cars_per], "total_laps": laps})

    return sessions


@router.get("/zones/{zone_id}/stage-sessions")
async def get_stage_sessions(zone_id: str, _auth=Depends(require_admin)):
    """Return all sessions for this zone grouped by stage, with phase status."""
    with get_db(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, type, total_laps, team_ids, phase, name FROM race_sessions "
            "WHERE zone_id=? ORDER BY rowid",
            (zone_id,),
        ).fetchall()
        team_count = db_get_zone_team_count(conn, zone_id)
        bracket = compute_bracket(team_count)
        current_stage = _determine_current_stage(conn, zone_id, bracket)

    sessions = []
    for r in rows:
        team_ids = json.loads(r["team_ids"]) if r["team_ids"] else []
        r_dict = dict(r)  # convert Row to dict for .get() safety
        sessions.append(
            {
                "id": r_dict["id"],
                "type": r_dict["type"],
                "total_laps": r_dict["total_laps"],
                "team_count": len(team_ids),
                "team_ids": team_ids,
                "phase": r_dict["phase"],
                "name": r_dict.get("name"),
            }
        )
    return {
        "zone_id": zone_id,
        "current_stage": current_stage,
        "sessions": sessions,
    }


# ---------------------------------------------------------------------------
# Zone-scoped race control
# ---------------------------------------------------------------------------


_VALID_STAGES = {"qualification", "placement", "group_stage", "semi", "final"}


@router.post("/zones/{zone_id}/create-race")
async def zone_create_race(
    zone_id: str,
    body: ZoneCreateRaceBody,
    _auth=Depends(require_admin),
):
    """管理员手动创建一场正赛（入队等待 worker 消费）。"""
    if body.session_type not in _VALID_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"session_type 必须是: {', '.join(_VALID_STAGES)}",
        )

    with get_db(DB_PATH) as conn:
        zone = db_get_zone(conn, zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail=f"赛区未找到: {zone_id}")

        # 验证队伍存在且有代码
        try:
            teams_data = db_get_teams_with_code(conn, body.team_ids)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        # 创建 races 记录
        race_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        db_create_race(
            conn,
            race_id=race_id,
            race_type=body.session_type,
            zone_id=zone_id,
            initiator=None,
            participant_ids=body.team_ids,
            world_key="complex",
            total_laps=body.total_laps,
            name=body.name,
            created_at=now,
        )

        # 创建 race_sessions 记录（worker 完成时更新 phase/result）
        db_upsert_session(
            conn,
            race_id,
            body.session_type,
            body.team_ids,
            body.total_laps,
            zone_id,
            name=body.name,
        )

    # 入队
    from server.blueprints.races import _enqueue_race

    _enqueue_race(race_id)

    return {
        "status": "created",
        "race_id": race_id,
        "session_type": body.session_type,
        "team_count": len(body.team_ids),
        "total_laps": body.total_laps,
        "name": body.name,
    }


@router.post("/zones/{zone_id}/set-session")
async def zone_set_session(
    zone_id: str,
    body: ZoneSetSessionBody,
    _auth=Depends(require_admin),
):
    _running_state_for(body.session_type)  # validate early

    with get_db(DB_PATH) as conn:
        zone = db_get_zone(conn, zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail=f"赛区未找到: {zone_id}")

        team_ids = (
            body.team_ids
            if body.team_ids is not None
            else db_get_zone_team_ids(conn, zone_id)
        )

        if body.total_laps is not None:
            total_laps = body.total_laps
        else:
            br = compute_bracket(len(team_ids))
            total_laps = br["laps_per_stage"].get(body.session_type, zone["total_laps"])
        try:
            teams_data = db_get_teams_with_code(conn, team_ids)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        db_upsert_session(
            conn,
            body.session_id,
            body.session_type,
            team_ids,
            total_laps,
            zone_id,
            name=body.name,
        )

    return {
        "status": "ready",
        "session_id": body.session_id,
        "zone_id": zone_id,
        "cars_count": len(teams_data),
    }


@router.post("/zones/{zone_id}/start-race")
async def zone_start_race(zone_id: str, _auth=Depends(require_admin)):
    sm = get_zone_sm(zone_id)

    # 报名阶段自动锁定提交，无需手动操作
    if sm.state == RaceState.REGISTRATION:
        sm.transition(RaceState.IDLE)

    with get_db(DB_PATH) as conn:
        row = db_get_waiting_session(conn, zone_id)

    if row is None:
        # Pre-create ALL sessions for the new stage
        with get_db(DB_PATH) as conn:
            team_count = db_get_zone_team_count(conn, zone_id)
            bracket = compute_bracket(team_count)
            stage = _determine_current_stage(conn, zone_id, bracket)
            if stage is None:
                raise HTTPException(
                    status_code=409, detail="所有阶段已完成，无法开始新比赛"
                )
            _pre_create_stage_sessions(conn, zone_id, stage, bracket)
            row = db_get_waiting_session(conn, zone_id)
            if row is None:
                raise HTTPException(status_code=500, detail="自动创建场次失败")

    session_id = row["id"]
    session_type = row["type"]
    total_laps = row["total_laps"]
    target_state = _running_state_for(session_type)

    try:
        sm.transition(target_state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    with get_db(DB_PATH) as conn:
        teams_data = db_get_teams_with_code(conn, row["team_ids"])
    cars = _build_cars(teams_data)
    if not cars:
        sm.reset()
        raise HTTPException(
            status_code=409, detail="No team code available. Call set-session first."
        )

    try:
        resp = await asyncio.to_thread(
            simnode_start_race, session_id, session_type, total_laps, cars
        )
    except RuntimeError as exc:
        sm.reset()
        raise HTTPException(status_code=503, detail=f"Sim Node unreachable: {exc}")

    now = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        db_mark_session_running(conn, session_id, now)

    _zone_running_session[zone_id] = session_id
    asyncio.create_task(_watch_simnode(session_id, session_type, zone_id))

    await _broadcast(
        "running", zone_id=zone_id, session_id=session_id, session_type=session_type
    )
    return {
        "status": "running",
        "session_id": session_id,
        "zone_id": zone_id,
        "stream_url": resp.get("stream_ws_url"),
    }


@router.post("/zones/{zone_id}/stop-race")
async def zone_stop_race(
    zone_id: str,
    request: Request,
    credentials: HTTPBasicCredentials = Depends(require_admin),
):
    """
    批量取消赛区内的比赛。
    新增审计日志，记录调用者 IP、用户名以及被取消的 session_id。
    """
    # 获取当前正在运行的 session_id
    session_id = _zone_running_session.get(zone_id)
    if not session_id:
        raise HTTPException(status_code=404, detail="No active race in this zone")

    # ---------- P0: 审计日志 ----------
    logger.warning(
        "[AUDIT] zone_stop_race: zone=%s session=%s client=%s user=%s",
        zone_id,
        session_id,
        request.client.host if request else "unknown",
        credentials.username if credentials else "unknown",
    )
    # ----------------------------------

    # 调用 SimNode 取消比赛
    await asyncio.to_thread(simnode_cancel_race, session_id)
    return {"status": "stopping", "zone_id": zone_id}


@router.post("/zones/{zone_id}/reset")
async def zone_reset(
    zone_id: str,
    request: Request,
    _auth=Depends(require_admin),
    credentials: HTTPBasicCredentials = Depends(require_admin),
):
    """
    重置赛区状态。为防止“幽灵” STOP 文件导致 admin_stop，
    先检查并取消正在运行的 SimNode 比赛。
    """
    # ---------- P1: 先取消正在运行的比赛 ----------
    if session_id := _zone_running_session.get(zone_id):
        await asyncio.to_thread(simnode_cancel_race, session_id)
    # ------------------------------------------------

    sm = get_zone_sm(zone_id)
    sm.reset()  # 只重置状态机
    _zone_running_session.pop(zone_id, None)  # 清除本地记录
    await _broadcast("idle", zone_id=zone_id)
    return {"status": "idle", "zone_id": zone_id}


@router.post("/zones/{zone_id}/finalize")
async def zone_finalize(zone_id: str, _auth=Depends(require_admin)):
    """推进赛程：计算下一阶段对阵，预创建所有场次，切回 IDLE。"""
    sm = get_zone_sm(zone_id)
    current = sm.state.value

    next_state_map = {
        "PLACEMENT_FINISHED": RaceState.PLACEMENT_DONE,
        "PLACEMENT_ABORTED": RaceState.PLACEMENT_DONE,
        "GROUP_STAGE_FINISHED": RaceState.GROUP_STAGE_DONE,
        "GROUP_STAGE_ABORTED": RaceState.GROUP_STAGE_DONE,
        "SEMI_FINISHED": RaceState.SEMI_DONE,
        "SEMI_ABORTED": RaceState.SEMI_DONE,
        "FINAL_FINISHED": RaceState.CLOSED,
    }
    next_state = next_state_map.get(current)
    if next_state is None:
        raise HTTPException(
            status_code=409, detail=f"当前状态 '{current}' 不支持 finalize 操作"
        )

    try:
        sm.transition(next_state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # 决赛结束 → 关闭赛事，无需创建下一阶段
    if next_state == RaceState.CLOSED:
        await _broadcast("closed", zone_id=zone_id)
        return {"state": sm.state.value, "zone_id": zone_id, "next_stage": None}

    # 计算下一阶段对阵，预创建所有 waiting 场次
    with get_db(DB_PATH) as conn:
        team_count = db_get_zone_team_count(conn, zone_id)
        bracket = compute_bracket(team_count)
        next_stage = _determine_current_stage(conn, zone_id, bracket)
        if next_stage:
            _pre_create_stage_sessions(conn, zone_id, next_stage, bracket)

    # 切回 IDLE，管理员可以点「开始比赛」逐个执行
    sm.reset()
    await _broadcast("idle", zone_id=zone_id)
    return {"state": sm.state.value, "zone_id": zone_id, "next_stage": next_stage}


# ---------------------------------------------------------------------------
# Watchers and handlers
# ---------------------------------------------------------------------------


async def _watch_simnode(session_id: str, session_type: str, zone_id: str = "default"):
    """Poll Sim Node status every 5s until race ends."""
    none_strikes = 0
    while True:
        await asyncio.sleep(5)
        status = await asyncio.to_thread(simnode_get_status, session_id)
        if status is None:
            none_strikes += 1
            if none_strikes >= 3:
                break
            continue
        none_strikes = 0
        if status == "completed":
            await _handle_finished(session_id, session_type, zone_id)
            break
        if status in ("error", "cancelled"):
            await _handle_aborted(session_id, session_type, zone_id)
            break


async def _handle_finished(
    session_id: str, session_type: str, zone_id: str = "default"
):
    sm = get_zone_sm(zone_id)
    try:
        sm.transition(_finished_state_for(session_type))
    except ValueError:
        pass

    rec_dir = pathlib.Path(RECORDINGS_DIR) / session_id
    meta_file = rec_dir / "metadata.json"
    recording_path = str(rec_dir.resolve())

    rec_dir.mkdir(parents=True, exist_ok=True)
    if meta_file.exists():
        try:
            result = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            result = {}
    else:
        result = await asyncio.to_thread(simnode_get_result, session_id) or {}

    result.setdefault("session_id", session_id)
    result.setdefault("session_type", session_type)
    result.setdefault("recording_path", recording_path)
    result.setdefault("recorded_at", datetime.datetime.now().isoformat())
    result["zone_id"] = zone_id

    meta_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    now = datetime.datetime.now().isoformat()
    _POINTS_TABLE = {1: 10, 2: 7, 3: 5, 4: 3}
    with get_db(DB_PATH) as conn:
        db_mark_session_finished(conn, session_id, now)
        from server.database.action import update_race_session as _update_race_session

        _update_race_session(conn, session_id, result=result)

        # Write race points ONLY for cars that finished the race
        final_rankings = result.get("final_rankings", [])
        finished_rank = 1
        for entry in final_rankings:
            team_id = entry.get("team_id")
            if not team_id:
                continue
            # 只给完赛的小车发放积分（total_time 不为 None）
            if entry.get("total_time") is not None:
                points = _POINTS_TABLE.get(finished_rank, 1)
                from server.database.action import upsert_race_points as _upsert_rp

                _upsert_rp(
                    conn,
                    session_id,
                    team_id,
                    finished_rank,
                    points,
                    best_lap_time=entry.get("best_lap"),
                )
                finished_rank += 1

    _zone_running_session.pop(zone_id, None)
    await _broadcast(
        "recording_ready",
        zone_id=zone_id,
        session_id=session_id,
        recording_path=recording_path,
    )

    # Auto-advance: queue next session or finalize stage
    asyncio.create_task(_after_race_complete(zone_id, session_type))


async def _after_race_complete(zone_id: str, stage: str):
    """After a race finishes: auto-create next session or finalize stage."""
    sm = get_zone_sm(zone_id)

    with get_db(DB_PATH) as conn:
        team_count = db_get_zone_team_count(conn, zone_id)
        bracket = compute_bracket(team_count)
        total = bracket["sessions_per_stage"].get(stage, 1)
        finished = conn.execute(
            "SELECT COUNT(*) FROM race_sessions "
            "WHERE zone_id=? AND type=? AND phase IN ('recording_ready','finished')",
            (zone_id, stage),
        ).fetchone()[0]

    if finished < total:
        # More waiting sessions already pre-created — go IDLE
        try:
            sm.transition(RaceState.IDLE)
        except ValueError:
            pass
    else:
        # All sessions done — stay in _FINISHED / _ABORTED,
        # wait for admin to click "推进赛程" (zone_finalize)
        pass

    await _broadcast(sm.state.value, zone_id=zone_id)


async def _handle_aborted(session_id: str, session_type: str, zone_id: str = "default"):
    sm = get_zone_sm(zone_id)
    try:
        sm.transition(_aborted_state_for(session_type))
    except ValueError:
        pass
    now = datetime.datetime.now().isoformat()

    rec_dir = pathlib.Path(RECORDINGS_DIR) / session_id
    meta_file = rec_dir / "metadata.json"
    telemetry_file = rec_dir / "telemetry.jsonl"
    if telemetry_file.exists() and not meta_file.exists():
        rec_dir.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "session_type": session_type,
                    "zone_id": zone_id,
                    "finish_reason": "aborted",
                    "recorded_at": now,
                    "teams": [],
                    "final_rankings": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        db_phase = "recording_ready"
    else:
        db_phase = "aborted"

    with get_db(DB_PATH) as conn:
        db_mark_session_aborted(conn, session_id, db_phase, now)
    _zone_running_session.pop(zone_id, None)
    await _broadcast("aborted", zone_id=zone_id, session_id=session_id)


# ---------------------------------------------------------------------------
# Per-zone registration open/close (独立于 code submission)
# ---------------------------------------------------------------------------


@router.post("/zones/{zone_id}/close-registration")
async def close_zone_registration(zone_id: str, _auth=Depends(require_admin)):
    """关闭指定赛区的队伍注册（不影响已注册队伍上传代码）。"""
    from server.database.action import db_set_zone_registration

    with get_db(DB_PATH) as conn:
        if not db_set_zone_registration(conn, zone_id, False):
            raise HTTPException(status_code=404, detail=f"赛区未找到: {zone_id}")
    return {"status": "registration_closed", "zone_id": zone_id}


@router.post("/zones/{zone_id}/open-registration")
async def open_zone_registration(zone_id: str, _auth=Depends(require_admin)):
    """打开指定赛区的队伍注册。"""
    from server.database.action import db_set_zone_registration

    with get_db(DB_PATH) as conn:
        if not db_set_zone_registration(conn, zone_id, True):
            raise HTTPException(status_code=404, detail=f"赛区未找到: {zone_id}")
    return {"status": "registration_opened", "zone_id": zone_id}


# ---------------------------------------------------------------------------
# Per-zone submission lock/unlock
# ---------------------------------------------------------------------------


@router.post("/zones/{zone_id}/lock-submissions")
async def lock_zone_submissions(zone_id: str, _auth=Depends(require_admin)):
    """锁定指定赛区的提交：将赛区状态从 REGISTRATION → IDLE。"""
    from server.race.state_machine import RaceState, get_zone_sm

    sm = get_zone_sm(zone_id)
    if sm.state != RaceState.REGISTRATION:
        raise HTTPException(
            status_code=409,
            detail=f"赛区 '{zone_id}' 当前状态为 {sm.state.value}，不是 REGISTRATION，无法锁定提交。",
        )
    sm.transition(RaceState.IDLE)
    return {"status": "locked", "zone_id": zone_id}


@router.post("/zones/{zone_id}/unlock-submissions")
async def unlock_zone_submissions(zone_id: str, _auth=Depends(require_admin)):
    """解锁指定赛区的提交：将赛区状态从 IDLE → REGISTRATION。"""
    from server.race.state_machine import RaceState, get_zone_sm

    sm = get_zone_sm(zone_id)
    if sm.state != RaceState.IDLE:
        raise HTTPException(
            status_code=409,
            detail=f"赛区 '{zone_id}' 当前状态为 {sm.state.value}，不是 IDLE，无法解锁提交。",
        )
    sm.transition(RaceState.REGISTRATION)
    return {"status": "unlocked", "zone_id": zone_id}


# ---------------------------------------------------------------------------
# Legacy endpoints (apply to all zones, backward compat)
# ---------------------------------------------------------------------------


@router.post("/lock-submissions")
async def lock_all_submissions(_auth=Depends(require_admin)):
    """锁定所有赛区提交：将所有 REGISTRATION 状态的赛区 → IDLE。"""
    from server.race.state_machine import RaceState, all_zone_ids, get_zone_sm

    locked = []
    for zone_id in all_zone_ids():
        sm = get_zone_sm(zone_id)
        if sm.state == RaceState.REGISTRATION:
            sm.transition(RaceState.IDLE)
            locked.append(zone_id)

    return {"status": "locked", "zones_locked": locked}


@router.post("/unlock-submissions")
async def unlock_all_submissions(_auth=Depends(require_admin)):
    """解锁所有赛区提交：将所有 IDLE 状态的赛区 → REGISTRATION。"""
    from server.race.state_machine import RaceState, all_zone_ids, get_zone_sm

    unlocked = []
    for zone_id in all_zone_ids():
        sm = get_zone_sm(zone_id)
        if sm.state == RaceState.IDLE:
            sm.transition(RaceState.REGISTRATION)
            unlocked.append(zone_id)

    return {"status": "unlocked", "zones_unlocked": unlocked}


@router.post("/set-session")
async def set_session(body: SetSessionBody, _auth=Depends(require_admin)):
    zone_body = ZoneSetSessionBody(
        session_type=body.session_type,
        session_id=body.session_id,
        team_ids=body.team_ids,
        total_laps=body.total_laps,
    )
    with get_db(DB_PATH) as conn:
        db_ensure_default_zone(conn, datetime.datetime.now().isoformat())
    return await zone_set_session("default", zone_body, _auth)


@router.post("/start-race")
async def start_race(_auth=Depends(require_admin)):
    return await zone_start_race("default", _auth)


@router.post("/stop-race")
async def stop_race(_auth=Depends(require_admin)):
    return await zone_stop_race("default", _auth)


@router.post("/reset-track")
async def reset_track(_auth=Depends(require_admin)):
    return await zone_reset("default", _auth)


@router.get("/standings")
async def get_standings(_auth=Depends(require_admin)):
    return await get_zone_standings("default", _auth)


@router.post("/finalize-placement")
async def finalize_placement(_auth=Depends(require_admin)):
    sm = get_zone_sm("default")
    try:
        sm.transition(RaceState.PLACEMENT_DONE)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle", zone_id="default")
    return {"state": sm.state}


@router.post("/finalize-group-stage")
async def finalize_group_stage(_auth=Depends(require_admin)):
    sm = get_zone_sm("default")
    try:
        sm.transition(RaceState.GROUP_STAGE_DONE)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle", zone_id="default")
    return {"state": sm.state}


@router.post("/finalize-semi")
async def finalize_semi(_auth=Depends(require_admin)):
    sm = get_zone_sm("default")
    try:
        sm.transition(RaceState.SEMI_DONE)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle", zone_id="default")
    return {"state": sm.state}


@router.post("/close-event")
async def close_event(_auth=Depends(require_admin)):
    sm = get_zone_sm("default")
    try:
        sm.transition(RaceState.CLOSED)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await _broadcast("idle", zone_id="default")
    return {"state": sm.state}


# ---------------------------------------------------------------------------
# Test race global switch
# ---------------------------------------------------------------------------


@router.post("/disable-test-races")
async def disable_test_races(_auth=Depends(require_admin)):
    """关闭测试赛（正赛期间使用，避免与赛程竞争）。"""
    from server.blueprints.races import set_test_race_enabled

    set_test_race_enabled(False)
    return {"status": "test_races_disabled"}


@router.post("/enable-test-races")
async def enable_test_races(_auth=Depends(require_admin)):
    """打开测试赛。"""
    from server.blueprints.races import set_test_race_enabled

    set_test_race_enabled(True)
    return {"status": "test_races_enabled"}


@router.get("/test-races-status")
async def get_test_races_status(_auth=Depends(require_admin)):
    """查询当前测试赛开关状态。"""
    from server.blueprints.races import is_test_race_enabled

    return {"enabled": is_test_race_enabled()}


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


@router.post("/change-password")
async def change_password(body: ChangePasswordBody, _auth=Depends(require_admin)):
    """修改管理员密码。需要提供旧密码验证和新密码。"""
    from server.config.config import Config

    if not body.old_password or not body.new_password:
        raise HTTPException(status_code=400, detail="旧密码和新密码均为必填项")

    if not secrets.compare_digest(body.old_password.encode(), ADMIN_PASSWORD.encode()):
        raise HTTPException(status_code=403, detail="旧密码错误")

    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="新密码长度至少为4位")

    try:
        Config.set_admin_password(body.new_password)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"密码写入配置文件失败: {e}")

    return {"status": "ok", "message": "密码修改成功，请使用新密码重新登录"}


# ---------------------------------------------------------------------------
# GET /api/admin/live-frame/{session_id} — proxy overhead camera JPEG
# ---------------------------------------------------------------------------


@router.get("/live-frame/{session_id}")
async def get_live_frame(session_id: str, _auth=Depends(require_admin)):
    """Proxy overhead camera frame from simnode. Reuses shared HTTP connection pool."""
    try:
        resp = await _get_race_frame_async(session_id)
        if resp is None:
            raise HTTPException(status_code=503, detail="Simnode unreachable")
        return Response(
            content=resp,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Simnode unreachable")


# ---------------------------------------------------------------------------
# Admin view team code — view any team's submitted controller code
# ---------------------------------------------------------------------------


@router.get("/team-code/{team_id}")
async def view_team_code(team_id: str, _auth=Depends(require_admin)):
    """获取指定队伍所有槽位的提交代码内容。"""
    from server.database.action import db_get_all_slots_code

    with get_db(DB_PATH) as conn:
        slots = db_get_all_slots_code(conn, team_id)

    result = []
    for slot in slots:
        code = ""
        code_path = slot.get("code_path")
        if code_path and pathlib.Path(code_path).exists():
            code = pathlib.Path(code_path).read_text(encoding="utf-8")
        result.append(
            {
                "slot_name": slot["slot_name"],
                "submitted_at": slot["submitted_at"],
                "is_race_active": bool(slot["is_race_active"]),
                "code": code,
            }
        )

    if not result:
        raise HTTPException(status_code=404, detail=f"队伍 {team_id} 尚无提交代码")

    return {"team_id": team_id, "slots": result}


# ---------------------------------------------------------------------------
# Admin impersonate team — view any team's submission dashboard
# ---------------------------------------------------------------------------


@router.post("/impersonate/{team_id}")
async def impersonate_team(team_id: str, _auth=Depends(require_admin)):
    """生成一个临时 token，管理员可用此 token 以队伍身份登录提交界面。"""
    from server.database.action import db_get_team_secure

    with get_db(DB_PATH) as conn:
        team = db_get_team_secure(conn, team_id)

    if team is None:
        raise HTTPException(status_code=404, detail=f"队伍不存在: {team_id}")

    _cleanup_expired_tokens()
    token = secrets.token_urlsafe(32)
    _impersonate_tokens[token] = {
        "team_id": team_id,
        "team_name": team["name"],
        "zone_id": team["zone_id"],
        "expires_at": time.time() + 300,  # 5 minutes
    }

    return {
        "token": token,
        "team_id": team_id,
        "team_name": team["name"],
        "zone_id": team["zone_id"],
    }


# ---------------------------------------------------------------------------
# Admin delete team — remove a team and all its associated data
# ---------------------------------------------------------------------------


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, _auth=Depends(require_admin)):
    """删除队伍及其所有关联数据（提交记录、测试记录、积分等）。"""
    with get_db(DB_PATH) as conn:
        if not db_delete_team(conn, team_id):
            raise HTTPException(status_code=404, detail=f"队伍不存在: {team_id}")
    return {"status": "deleted", "team_id": team_id}

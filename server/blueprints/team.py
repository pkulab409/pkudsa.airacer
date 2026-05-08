"""
Team and zone public endpoints.
No auth required — read-only public data.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.config.config import DB_PATH
from server.database.action import (
    create_team,
    db_get_running_session,
    db_get_teams_by_zone,
    db_get_zone_detailed,
    db_get_zone_standings,
    db_list_zones,
    db_resource_exists,
    list_teams as db_list_all_teams,
)
from server.database.models import get_db
from server.race.bracket import compute_bracket
from server.race.state_machine import get_zone_sm

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    zone_id:   str
    team_id:   str
    team_name: str
    password:  str


# ---------------------------------------------------------------------------
# GET /api/zones — public zone list
# ---------------------------------------------------------------------------

@router.get("/zones")
async def list_zones():
    with get_db(DB_PATH) as conn:
        rows = db_list_zones(conn)

    result = []
    for r in rows:
        sm = get_zone_sm(r["id"])
        result.append({
            "id":          r["id"],
            "name":        r["name"],
            "description": r["description"],
            "total_laps":  r["total_laps"],
            "created_at":  r["created_at"],
            "team_count":  r["team_count"],
            "state":       sm.state.value,
        })
    return result


# ---------------------------------------------------------------------------
# GET /api/zones/{zone_id} — single zone public detail
# ---------------------------------------------------------------------------

@router.get("/zones/{zone_id}")
async def get_zone(zone_id: str):
    with get_db(DB_PATH) as conn:
        result = db_get_zone_detailed(conn, zone_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"赛区未找到: {zone_id}")

    sm = get_zone_sm(zone_id)
    teams_list = [{"id": t["id"], "name": t["name"]} for t in result["teams"]]
    return {
        "id":          result["id"],
        "name":        result["name"],
        "description": result["description"],
        "total_laps":  result["total_laps"],
        "created_at":  result["created_at"],
        "state":       sm.state.value,
        "teams":       teams_list,
        "standings":   result["standings"],
        "bracket":     compute_bracket(len(teams_list)),
    }


# ---------------------------------------------------------------------------
# GET /api/zones/{zone_id}/status — live phase info for audience
# ---------------------------------------------------------------------------

@router.get("/zones/{zone_id}/status")
async def get_zone_status(zone_id: str):
    sm = get_zone_sm(zone_id)
    state = sm.state.value

    with get_db(DB_PATH) as conn:
        running = db_get_running_session(conn, zone_id)

    return {
        "zone_id": zone_id,
        "phase": state,
        "state": state,
        "running_session_id": running["id"] if running else None,
    }


# ---------------------------------------------------------------------------
# GET /api/zones/{zone_id}/qualifying-results — placement standings for audience
# ---------------------------------------------------------------------------

@router.get("/zones/{zone_id}/qualifying-results")
async def get_qualifying_results(zone_id: str):
    with get_db(DB_PATH) as conn:
        results = db_get_zone_standings(conn, zone_id)

    return {
        "zone_id": zone_id,
        "results": results,
    }


# ---------------------------------------------------------------------------
# POST /api/register — team self-registration
# ---------------------------------------------------------------------------

@router.post("/register")
async def register_team(body: RegisterRequest):
    import re
    import bcrypt as _bcrypt

    if not body.zone_id or not body.team_id or not body.team_name or not body.password:
        raise HTTPException(status_code=400, detail="所有字段均为必填")

    if not re.match(r'^[a-zA-Z0-9_]{2,20}$', body.team_id):
        raise HTTPException(
            status_code=400,
            detail="队伍ID只允许字母/数字/下划线，长度2-20"
        )

    password_hash = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()

    with get_db(DB_PATH) as conn:
        if not db_resource_exists(conn, "zones", body.zone_id):
            raise HTTPException(status_code=404, detail=f"赛区不存在: {body.zone_id}")

        if db_resource_exists(conn, "teams", body.team_id):
            raise HTTPException(status_code=409, detail=f"队伍ID已被占用: {body.team_id}")

        create_team(conn, body.team_id, body.team_name, password_hash, body.zone_id)

    return {"status": "registered", "team_id": body.team_id, "zone_id": body.zone_id}


# ---------------------------------------------------------------------------
# GET /api/teams — list all teams (optionally filtered by zone)
# ---------------------------------------------------------------------------

@router.get("/teams")
async def list_teams(zone_id: str = None):
    with get_db(DB_PATH) as conn:
        if zone_id:
            rows = db_get_teams_by_zone(conn, zone_id)
        else:
            rows = db_list_all_teams(conn)
    return [{"id": r["id"], "name": r["name"], "zone_id": r["zone_id"]} for r in rows]

"""
Races blueprint — 统一赛事 API（测试赛事 + 后续正赛统一入口）

POST   /api/races            — 创建一场新的比赛（用户发起的测试赛事）
GET    /api/races/{race_id}  — 查询单场比赛状态/结果
GET    /api/races            — 查询某队伍参与的比赛列表 (?team_id=xxx)
"""

import datetime
import json
import threading
import uuid
from typing import Optional

# 全局开关：是否允许发起测试赛（正赛期间应关闭，避免竞争）
test_race_enabled: bool = True
_test_race_lock = threading.Lock()


def set_test_race_enabled(enabled: bool) -> None:
    global test_race_enabled
    with _test_race_lock:
        test_race_enabled = enabled


def is_test_race_enabled() -> bool:
    with _test_race_lock:
        return test_race_enabled


from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from server.blueprints.submission import (
    VALID_WORLDS,
    _validate_impersonation_bearer,
    _verify_password,
)
from server.config.config import DB_PATH
from server.database.action import (
    create_race as db_create_race,
)
from server.database.action import (
    db_count_active_races_by_initiator,
    db_get_team_secure,
    db_get_teams_with_code,
    list_races_by_participant,
)
from server.database.action import (
    get_race as db_get_race,
)
from server.database.models import get_db

router = APIRouter()

TEST_RACE_LAPS_MIN = 1
TEST_RACE_LAPS_MAX = 2

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateRaceRequest(BaseModel):
    team_id: str
    password: str
    world: str = "complex"  # "basic" | "complex"
    total_laps: int = 2
    opponents: list[str] = []  # 对手 team_id 列表（不含发起者）
    name: Optional[str] = None  # 自定义名称/备注


class RaceResponse(BaseModel):
    race_id: str
    type: str
    status: str
    zone_id: str
    initiator: Optional[str] = None
    participants: list[str]
    world_key: str
    total_laps: int
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    finish_reason: Optional[str] = None
    result: Optional[dict] = None
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# 内存队列：worker 消费
# ---------------------------------------------------------------------------

_race_queue: list[str] = []  # race_id 列表
_race_queue_lock = threading.Lock()


def _enqueue_race(race_id: str) -> int:
    with _race_queue_lock:
        _race_queue.append(race_id)
        return len(_race_queue)


def _dequeue_race() -> Optional[str]:
    with _race_queue_lock:
        return _race_queue.pop(0) if _race_queue else None


# ---------------------------------------------------------------------------
# POST /api/races — 创建测试赛事
# ---------------------------------------------------------------------------


@router.post("/api/races")
async def create_race(body: CreateRaceRequest):
    """用户发起一场测试赛事。"""
    # 0. 检查全局开关
    if not is_test_race_enabled():
        raise HTTPException(
            status_code=403,
            detail="测试赛已关闭，当前正在进行正赛赛程，无法发起测试赛",
        )

    # 1. 校验参数
    world_key = body.world.lower()
    if world_key not in VALID_WORLDS:
        raise HTTPException(
            status_code=400,
            detail=f"world must be one of: {', '.join(VALID_WORLDS)}",
        )
    if body.total_laps < TEST_RACE_LAPS_MIN or body.total_laps > TEST_RACE_LAPS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"total_laps must be between {TEST_RACE_LAPS_MIN} and {TEST_RACE_LAPS_MAX}",
        )

    # 2. 验证身份
    with get_db(DB_PATH) as conn:
        team_row = db_get_team_secure(conn, body.team_id)
    if team_row is None:
        raise HTTPException(status_code=401, detail="Team not found")
    if not _verify_password(
        body.password, team_row["password_hash"]
    ) and not _validate_impersonation_bearer(body.password, body.team_id):
        raise HTTPException(status_code=401, detail="Invalid password")

    zone_id = team_row["zone_id"]
    if not zone_id:
        raise HTTPException(status_code=400, detail="Team has no zone assigned")

    # 3. 检查该队伍是否已有正在进行的测试赛事（防恶意并发）
    with get_db(DB_PATH) as conn:
        active_count = db_count_active_races_by_initiator(conn, body.team_id)
    if active_count > 0:
        raise HTTPException(
            status_code=429,
            detail="该队伍已有正在进行的测试赛事，请等待完成后重试",
        )

    # 4. 拼 participant_ids = 发起者 + 对手（去重）
    all_teams = list(dict.fromkeys([body.team_id] + body.opponents))
    if len(all_teams) < 1:
        raise HTTPException(
            status_code=400,
            detail="需要至少 1 支队伍才能发起测试赛事",
        )
    if len(all_teams) > 6:
        raise HTTPException(
            status_code=400,
            detail="最多支持 6 支队伍参赛",
        )

    # 5. 验所有参与者都有已上传的代码
    with get_db(DB_PATH) as conn:
        try:
            db_get_teams_with_code(conn, all_teams)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # 6. 写入 DB + 入队
    race_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with get_db(DB_PATH) as conn:
        db_create_race(
            conn,
            race_id=race_id,
            race_type="test",
            zone_id=zone_id,
            initiator=body.team_id,
            participant_ids=all_teams,
            world_key=world_key,
            total_laps=body.total_laps,
            name=body.name,
            created_at=now,
        )

    queue_pos = _enqueue_race(race_id)

    return {
        "status": "created",
        "race_id": race_id,
        "queue_position": queue_pos,
    }


# ---------------------------------------------------------------------------
# GET /api/races/{race_id} — 查询单个比赛的详情/结果
# ---------------------------------------------------------------------------


@router.get("/api/races/{race_id}")
async def get_race_detail(race_id: str):
    with get_db(DB_PATH) as conn:
        race = db_get_race(conn, race_id)
    if race is None:
        raise HTTPException(status_code=404, detail="Race not found")

    result = json.loads(race["result"]) if race["result"] else None
    participants = (
        json.loads(race["participant_ids"])
        if isinstance(race["participant_ids"], str)
        else race["participant_ids"]
    )

    return RaceResponse(
        race_id=race["id"],
        type=race["type"],
        status=race["status"],
        zone_id=race["zone_id"],
        initiator=race["initiator"],
        participants=participants,
        world_key=race["world_key"],
        total_laps=race["total_laps"],
        created_at=race["created_at"],
        started_at=race["started_at"],
        finished_at=race["finished_at"],
        finish_reason=race["finish_reason"],
        result=result,
        name=race.get("name"),
    )


# ---------------------------------------------------------------------------
# GET /api/races — 查询某队伍参与的所有比赛
# ---------------------------------------------------------------------------


@router.get("/api/races")
async def list_races(
    team_id: str = Query(...),
    limit: int = Query(default=20, le=50),
):
    with get_db(DB_PATH) as conn:
        rows = list_races_by_participant(conn, team_id, limit)
    results = []
    for r in rows:
        result = json.loads(r["result"]) if r["result"] else None
        participants = (
            json.loads(r["participant_ids"])
            if isinstance(r["participant_ids"], str)
            else r["participant_ids"]
        )
        results.append(
            RaceResponse(
                race_id=r["id"],
                type=r["type"],
                status=r["status"],
                zone_id=r["zone_id"],
                initiator=r["initiator"],
                participants=participants,
                world_key=r["world_key"],
                total_laps=r["total_laps"],
                created_at=r["created_at"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                finish_reason=r["finish_reason"],
                result=result,
                name=r.get("name"),
            )
        )
    return {"races": results}

"""
app.py — AI Racer Backend 应用主入口

运行方式（从项目根目录）：
    uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.config.config import DB_PATH, SERVER_HOST, SERVER_PORT
from server.database.models import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastApi生命周期，yield前面为启动时执行，yield后面为关闭时执行
    启动时：加载或创建数据库，恢复赛区状态，启动心跳和模拟直播任务
    关闭时：取消心跳和模拟直播任务
    """
    pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)

    # Wire state-machine persistence to the database and restore all zone states
    from server.race.state_machine import get_zone_sm, set_db_path

    set_db_path(DB_PATH)
    _restore_zone_states()

    hb_task = asyncio.create_task(_heartbeat_loop())
    live_task = asyncio.create_task(_sim_live_loop())
    test_task = asyncio.create_task(_serve_test_queue())
    race_task = asyncio.create_task(_serve_race_event_queue())
    yield
    for t in (hb_task, live_task, test_task, race_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


def _restore_zone_states() -> None:
    """Pre-load all zone StateMachines from the database so running states
    are known to the live-poll loop immediately after startup."""
    import sqlite3

    from server.race.state_machine import RaceState, get_zone_sm

    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            rows = conn.execute("SELECT id, state FROM zones").fetchall()
    except Exception:
        return

    for zone_id, state_str in rows:
        sm = get_zone_sm(zone_id)
        # If the zone was in a running state at shutdown, reset it to IDLE
        # (the race engine is gone after restart)
        try:
            state = RaceState(state_str)
        except ValueError:
            continue
        if state.value.endswith("_RUNNING"):
            sm.reset()  # persist to DB
        # For all other states, get_zone_sm already loaded them from DB


"""实例化应用"""
app = FastAPI(title="AI Racer Backend", version="1.0.0", lifespan=lifespan)

"""添加中间件，允许跨域请求（开发时）"""
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from server.blueprints.admin import router as admin_router
from server.blueprints.races import router as races_router
from server.blueprints.recording import router as recording_router
from server.blueprints.submission import router as submission_router
from server.blueprints.team import router as team_router
from server.ws.admin import router as ws_router

"""注册子路由"""
app.include_router(submission_router)  # 学生代码提交
app.include_router(admin_router)  # 管理员
app.include_router(recording_router)  # 录像
app.include_router(team_router)  # 队伍
app.include_router(races_router)  # 统一赛事
app.include_router(ws_router)  # 管理员WebSocket

# ---------------------------------------------------------------------------
# Static frontend (mounted last)
# ---------------------------------------------------------------------------

"""注册静态前端： / 直接定向到 /frontend/index.html，其余静态文件到 /frontend下"""
_frontend = pathlib.Path(__file__).resolve().parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


# ---------------------------------------------------------------------------
# Heartbeat: re-broadcast last known state every 10 s per zone
# ---------------------------------------------------------------------------


async def _heartbeat_loop() -> None:
    from server.ws.admin import manager

    while True:
        await asyncio.sleep(10)
        for msg in list(manager._last_msg_per_zone.values()):
            await manager.broadcast({**msg})


# ---------------------------------------------------------------------------
# Live telemetry: poll simnode every 1 s for all running zones
# ---------------------------------------------------------------------------


async def _serve_test_queue() -> None:
    """启动测试队列消费者 worker（旧式 test_runs）。"""
    from server.services.test_worker import _test_worker_loop

    await _test_worker_loop()


async def _serve_race_event_queue() -> None:
    """启动统一 race 事件队列消费者 worker。"""
    from server.services.test_worker import _race_event_worker_loop

    await _race_event_worker_loop()


async def _sim_live_loop() -> None:
    from server.blueprints.admin import _get_running_session_id
    from server.race.state_machine import all_running_zones
    from server.utils.simnode_client import get_race_live_info_async  # 改用异步版
    from server.ws.admin import manager

    while True:
        for zone_id, sm in all_running_zones():
            session_id = _get_running_session_id(zone_id)
            if not session_id:
                continue
            try:
                info = await get_race_live_info_async(session_id, timeout=1.5)
                # Re-check after blocking call to avoid overwriting a final state
                if info and sm.is_running():
                    base = manager._last_msg_per_zone.get(zone_id, {})
                    # Convert cars array to vehicles object {team_id: {...}}
                    vehicles = {}
                    for car in info.get("cars", []):
                        tid = car.get("team_id", "")
                        vehicles[tid] = {
                            "lap": car.get("lap"),
                            "checkpoints_passed": car.get("checkpoints_passed"),
                            "speed": car.get("speed"),
                            "status": car.get("status"),
                        }
                    # 区分"仿真引擎启动中"和"正常运行"两种状态：
                    # sim_time 为 None 说明 Webots 还没开始写 live.json（仿真引擎正在加载）
                    sim_time = info.get("sim_time")
                    warmup = sim_time is None
                    await manager.broadcast(
                        {
                            **base,
                            "type": "sim_status",
                            "zone_id": zone_id,
                            "webots_pid": info.get("webots_pid"),
                            "sim_time": sim_time or 0,
                            "vehicles": vehicles,
                            "warmup": warmup,  # 前端可据此显示"仿真引擎启动中..."
                        }
                    )
            except Exception:
                pass
        await asyncio.sleep(0.2)

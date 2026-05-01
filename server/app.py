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
    启动时：加载或创建数据库，启动心跳和模拟直播任务
    关闭时：取消心跳和模拟直播任务
    """
    pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)

    hb_task = asyncio.create_task(_heartbeat_loop())
    live_task = asyncio.create_task(_sim_live_loop())
    yield
    for t in (hb_task, live_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


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
from server.blueprints.recording import router as recording_router
from server.blueprints.submission import router as submission_router
from server.blueprints.team import router as team_router
from server.ws.admin import router as ws_router

"""注册子路由"""
app.include_router(submission_router)  # 学生代码提交
app.include_router(admin_router)  # 管理员
app.include_router(recording_router)  # 录像
app.include_router(team_router)  # 队伍
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
# Live telemetry: poll simnode every 3 s for all running zones
# ---------------------------------------------------------------------------


async def _sim_live_loop() -> None:
    from server.blueprints.admin import _get_running_session_id
    from server.race.state_machine import all_running_zones
    from server.utils.simnode_client import get_race_live_info
    from server.ws.admin import manager

    while True:
        await asyncio.sleep(3)
        for zone_id, sm in all_running_zones():
            session_id = _get_running_session_id(zone_id)
            if not session_id:
                continue
            try:
                info = await asyncio.to_thread(get_race_live_info, session_id)
                # Re-check after blocking call to avoid overwriting a final state
                if info and sm.is_running():
                    base = manager._last_msg_per_zone.get(zone_id, {})
                    await manager.broadcast(
                        {
                            **base,
                            "type": "sim_status",
                            "zone_id": zone_id,
                            "webots_pid": info.get("webots_pid"),
                            "sim_time_approx": int(info.get("sim_time") or 0),
                            "live_cars": info.get("cars", []),
                        }
                    )
            except Exception:
                pass

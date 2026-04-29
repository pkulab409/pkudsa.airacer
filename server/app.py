"""
app.py — AI Racer Backend 应用主入口，对应 Avalon 的 app.py

职责：
  - 创建 FastAPI 应用实例（对应 Avalon Flask 应用初始化）
  - 注册所有 Blueprint 路由（对应 Avalon blueprints 注册）
  - 初始化数据库（对应 Avalon db.init_app）
  - 启动 WebSocket 心跳后台任务

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
    pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)

    hb_task   = asyncio.create_task(_heartbeat_loop())
    live_task = asyncio.create_task(_sim_live_loop())
    yield
    for t in (hb_task, live_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title="AI Racer Backend", version="1.0.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS（开发阶段允许所有来源）
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 挂载蓝图（对应 Avalon app.register_blueprint）
# ---------------------------------------------------------------------------

from server.blueprints.submission import router as submission_router
from server.blueprints.admin      import router as admin_router
from server.blueprints.recording  import router as recording_router
from server.ws.admin              import router as ws_router

app.include_router(submission_router)
app.include_router(admin_router)
app.include_router(recording_router)
app.include_router(ws_router)

# ---------------------------------------------------------------------------
# 前端静态文件（最后挂载，不遮盖 API 路由）
# ---------------------------------------------------------------------------

_frontend = pathlib.Path(__file__).resolve().parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


# ---------------------------------------------------------------------------
# Admin WebSocket 心跳（对应 Avalon 的 socketio 心跳）
# ---------------------------------------------------------------------------

async def _heartbeat_loop() -> None:
    """Re-broadcast last known state every 10 s (keepalive for idle clients)."""
    from server.ws.admin import manager

    while True:
        await asyncio.sleep(10)
        await manager.broadcast({**manager._last_msg})


async def _sim_live_loop() -> None:
    """Poll simnode every 3 s during a running race; push PID, sim_time, car states."""
    from server.ws.admin import manager
    from server.race.state_machine import state_machine
    from server.utils.simnode_client import get_race_live_info

    while True:
        await asyncio.sleep(3)
        if not state_machine.is_running():
            continue
        last = manager._last_msg
        session_id = last.get("session_id")
        if not session_id:
            continue
        try:
            info = await asyncio.to_thread(get_race_live_info, session_id)
            # Re-check after the blocking call: a stop/abort may have fired while we
            # were waiting for simnode.  Broadcasting the stale "running" last-msg
            # at this point would overwrite the final state and freeze the UI.
            if info and state_machine.is_running():
                await manager.broadcast({
                    **manager._last_msg,   # use current snapshot, not the pre-I/O one
                    "type":            "sim_status",
                    "webots_pid":      info.get("webots_pid"),
                    "sim_time_approx": int(info.get("sim_time") or 0),
                    "live_cars":       info.get("cars", []),
                })
        except Exception:
            pass

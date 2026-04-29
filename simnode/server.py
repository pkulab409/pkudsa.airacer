import asyncio
import json
import logging
import pathlib
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from simnode.race_manager import RaceManager
from simnode.config.config import Config

logging.basicConfig(level=Config.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Racer Sim Node", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket 连接池：race_id → set[WebSocket]
_ws_connections: Dict[str, set] = {}
_ws_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class CarSpec(BaseModel):
    car_slot:  str
    team_id:   str
    team_name: str
    code_b64:  str   # Base64 编码的 team_controller.py 源码


class RaceCreateRequest(BaseModel):
    race_id:      str
    session_type: str    # qualifying / group_race / semi / final / test
    total_laps:   int
    cars:         List[CarSpec]


class RaceCreateResponse(BaseModel):
    status:        str
    race_id:       str
    stream_ws_url: str


# ---------------------------------------------------------------------------
# WebSocket 推流
# ---------------------------------------------------------------------------

def _make_ws_push_callback(race_id: str):
    def _push(snapshot: dict) -> None:
        connections = _ws_connections.get(race_id, set())
        if not connections:
            return
        msg = json.dumps(snapshot, ensure_ascii=False)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast(race_id, msg), loop)
    return _push


async def _broadcast(race_id: str, message: str) -> None:
    connections = _ws_connections.get(race_id, set())
    dead = set()
    for ws in connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    async with _ws_lock:
        for ws in dead:
            _ws_connections.get(race_id, set()).discard(ws)


# ---------------------------------------------------------------------------
# POST /race/create
# ---------------------------------------------------------------------------

@app.post("/race/create", response_model=RaceCreateResponse)
async def create_race(body: RaceCreateRequest):
    manager = RaceManager()

    async with _ws_lock:
        if body.race_id not in _ws_connections:
            _ws_connections[body.race_id] = set()

    ws_callback = _make_ws_push_callback(body.race_id)
    cars_data = [c.dict() for c in body.cars]

    try:
        manager.start_race(
            race_id=body.race_id,
            session_type=body.session_type,
            total_laps=body.total_laps,
            cars=cars_data,
            ws_push_callback=ws_callback,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception(f"启动比赛 {body.race_id} 失败")
        raise HTTPException(status_code=500, detail=str(e))

    host = Config.get("SIMNODE_HOST", "localhost:8001")
    stream_url = f"ws://{host}/race/{body.race_id}/stream"

    return RaceCreateResponse(
        status="started",
        race_id=body.race_id,
        stream_ws_url=stream_url,
    )


# ---------------------------------------------------------------------------
# POST /race/{race_id}/cancel
# ---------------------------------------------------------------------------

@app.post("/race/{race_id}/cancel")
async def cancel_race(race_id: str):
    manager = RaceManager()
    # Run blocking graceful-stop in a thread so the event loop stays responsive
    # (manager.cancel_race waits up to 35 s for Webots to exit)
    ok = await asyncio.to_thread(manager.cancel_race, race_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"比赛未找到或已结束: {race_id}")
    return {"status": "cancelled", "race_id": race_id}


# ---------------------------------------------------------------------------
# GET /race/{race_id}/status
# ---------------------------------------------------------------------------

@app.get("/race/{race_id}/status")
async def get_race_status(race_id: str):
    manager = RaceManager()
    status = manager.get_race_status(race_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"比赛未找到: {race_id}")
    return {"race_id": race_id, "status": status}


# ---------------------------------------------------------------------------
# GET /race/{race_id}/result
# ---------------------------------------------------------------------------

@app.get("/race/{race_id}/result")
async def get_race_result(race_id: str):
    manager = RaceManager()
    status = manager.get_race_status(race_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"比赛未找到: {race_id}")
    if status != "completed":
        raise HTTPException(status_code=425, detail=f"比赛尚未完成，当前状态: {status}")
    return manager.get_race_result(race_id)


# ---------------------------------------------------------------------------
# GET /race/{race_id}/live  — real-time PID + latest telemetry frame
# ---------------------------------------------------------------------------

@app.get("/race/{race_id}/live")
async def get_race_live(race_id: str):
    manager = RaceManager()
    status = manager.get_race_status(race_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Race not found: {race_id}")

    pid = manager.get_webots_pid(race_id)

    recordings_dir = pathlib.Path(Config.get("RECORDINGS_DIR", "./recordings")).resolve()
    telemetry_file = recordings_dir / race_id / "telemetry.jsonl"
    sim_time = None
    cars_live: List[Dict] = []

    if telemetry_file.exists():
        try:
            with open(telemetry_file, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                if size > 0:
                    chunk = min(size, 4096)
                    f.seek(-chunk, 2)
                    data = f.read().decode("utf-8", errors="replace")
                    lines = [ln for ln in data.split("\n") if ln.strip()]
                    if lines:
                        last = json.loads(lines[-1])
                        sim_time = last.get("t")
                        cars_live = last.get("cars", [])
        except Exception:
            pass

    return {
        "race_id":    race_id,
        "webots_pid": pid,
        "sim_time":   sim_time,
        "cars":       cars_live,
    }


# ---------------------------------------------------------------------------
# GET /race/{race_id}/frame  — latest overhead camera JPEG
# ---------------------------------------------------------------------------

@app.get("/race/{race_id}/frame")
async def get_race_frame(race_id: str):
    manager = RaceManager()
    status = manager.get_race_status(race_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Race not found: {race_id}")
    recordings_dir = pathlib.Path(Config.get("RECORDINGS_DIR", "./recordings")).resolve()
    frame_file = recordings_dir / race_id / "live_view.jpg"
    if not frame_file.exists():
        raise HTTPException(status_code=404, detail="No frame available yet")
    return FileResponse(
        str(frame_file),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# GET /races
# ---------------------------------------------------------------------------

@app.get("/races")
async def list_races():
    manager = RaceManager()
    races = manager.get_all_races()
    return [{"race_id": rid, "status": st} for rid, st in races]


# ---------------------------------------------------------------------------
# WS /race/{race_id}/stream
# ---------------------------------------------------------------------------

@app.websocket("/race/{race_id}/stream")
async def stream_race(websocket: WebSocket, race_id: str):
    await websocket.accept()

    async with _ws_lock:
        if race_id not in _ws_connections:
            _ws_connections[race_id] = set()
        _ws_connections[race_id].add(websocket)

    logger.info(f"WebSocket 已连接: race_id={race_id}")

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"type": "heartbeat"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: race_id={race_id}")
    finally:
        async with _ws_lock:
            _ws_connections.get(race_id, set()).discard(websocket)


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "simnode"}

#!/usr/bin/env python3
"""
Mock SimNode — 模拟仿真服务器。

复刻真实 simnode (simnode/server.py) 的全部 API 契约，
随机生成比赛遥测数据和最终排名，用于前端测试。

Usage:
    python scripts/mock_simnode.py [--port 8001]

Env vars:
    MOCK_RACE_DURATION  默认 "5,10" (min,max 秒)
    MOCK_SIM_SPEED      默认 3.0 (模拟时间倍率)
"""

import asyncio
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DURATION_RANGE = tuple(
    int(x) for x in os.getenv("MOCK_RACE_DURATION", "1,1").split(",")
)
SIM_SPEED = float(os.getenv("MOCK_SIM_SPEED", "3.0"))

# ---------------------------------------------------------------------------
# Coloured logging
# ---------------------------------------------------------------------------

C = {
    "G": "\033[92m",
    "Y": "\033[93m",
    "R": "\033[91m",
    "B": "\033[94m",
    "C": "\033[96m",
    "M": "\033[95m",
    "W": "\033[97m",
    "X": "\033[0m",
}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(color: str, event: str, msg: str = "") -> None:
    tag = f"{C[color]}[{event}]{C['X']}"
    print(f"{C['W']}[{_ts()}]{C['X']} {tag} {msg}", flush=True)


# ---------------------------------------------------------------------------
# Minimal valid JPEG (1x1 white pixel) — used for /frame endpoint
# ---------------------------------------------------------------------------

# Minimal valid JPEG (1x1 gray pixel) — generated at module load
_MINIMAL_JPEG: bytes = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09\x08"
    b"\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d"
    b"\x1a\x1c\x1c\x20\x24\x2e\x27\x20\x22\x2c\x23\x1c\x1c\x28\x37\x29\x2c"
    b"\x30\x31\x34\x34\x34\x1f\x27\x39\x3d\x38\x32\x3c\x2e\x33\x34\x32\xff"
    b"\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00"
    b"\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x10\x00"
    b"\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03"
    b'\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1'
    b"\xc1\x15R\xd1\xf0$3br\x82\x09\n\x16\x17\x18\x19\x1a%&'()*456789:CDE"
    b"FGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93"
    b"\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2"
    b"\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca"
    b"\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8"
    b"\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01"
    b"\x01\x00\x00?\x007\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\xff\xd9"
)


def _get_frame_jpeg() -> bytes:
    return _MINIMAL_JPEG


# ---------------------------------------------------------------------------
# Pydantic models (match real simnode)
# ---------------------------------------------------------------------------


class CarSpec(BaseModel):
    car_slot: str
    team_id: str
    team_name: str
    code_b64: str


class RaceCreateRequest(BaseModel):
    race_id: str
    session_type: str
    total_laps: int
    cars: list[CarSpec]


class RaceCreateResponse(BaseModel):
    status: str
    race_id: str
    stream_ws_url: str


# ---------------------------------------------------------------------------
# Mock race state
# ---------------------------------------------------------------------------


@dataclass
class MockRace:
    race_id: str
    session_type: str
    total_laps: int
    cars: list[dict]
    status: str = "waiting"
    start_time: float = 0.0
    duration: float = 20.0
    sim_time: float = 0.0
    max_sim_time: float = 60.0
    snapshots: list[dict] = field(default_factory=list)
    final_result: Optional[dict] = None
    cancel_flag: bool = False


# Global state
_race_store: dict[str, MockRace] = {}
_ws_connections: dict[str, set[WebSocket]] = {}
_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Mock SimNode", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Random data generators
# ---------------------------------------------------------------------------


def _rand_lap_count(total_laps: int) -> int:
    return random.randint(max(1, total_laps - 1), total_laps)


def _rand_best_lap() -> float:
    return round(random.uniform(20.0, 40.0), 2)


def _rand_total_time(laps: int, best_lap: float) -> float:
    return round(best_lap * laps * random.uniform(1.02, 1.10), 2)


def _gen_car_telemetry(
    car: dict, lap: int, lap_progress: float, sim_time: float
) -> dict:
    return {
        "team_id": car["team_id"],
        "x": round(random.uniform(-8.0, 8.0), 2),
        "y": round(random.uniform(-8.0, 8.0), 2),
        "heading": round(random.uniform(0, 6.283), 3),
        "speed": round(random.uniform(2.0, 14.0), 1),
        "lap": lap,
        "lap_progress": round(lap_progress, 3),
        "status": "normal",
        "boost_remaining": round(random.uniform(0, 100), 0),
    }


def _gen_final_rankings(cars: list[dict], total_laps: int) -> list[dict]:
    entries = []
    for car in cars:
        laps = _rand_lap_count(total_laps)
        best_lap = _rand_best_lap()
        total_time = _rand_total_time(laps, best_lap)
        collisions = random.randint(0, 3)
        status = "normal" if random.random() > 0.1 else "stopped"
        entries.append(
            {
                "team_id": car["team_id"],
                "team_name": car["team_name"],
                "laps": laps,
                "best_lap": best_lap,
                "total_time": total_time,
                "status": status,
                "collision_major_count": collisions,
            }
        )

    # Sort: finished first (by total_time ASC), then unfinished (by laps DESC)
    finished = sorted(
        [e for e in entries if e["status"] == "normal"],
        key=lambda e: e["total_time"],
    )
    unfinished = sorted(
        [e for e in entries if e["status"] != "normal"],
        key=lambda e: -e["laps"],
    )
    ranked = finished + unfinished
    for i, e in enumerate(ranked):
        e["rank"] = i + 1
    return ranked


# ---------------------------------------------------------------------------
# Race simulation (background coroutine)
# ---------------------------------------------------------------------------


async def _run_race_simulation(race: MockRace) -> None:
    race.status = "running"
    race.start_time = time.time()
    race.max_sim_time = random.uniform(30.0, 80.0)

    log(
        "C",
        "RACE START",
        f"{race.race_id}  cars={len(race.cars)}  laps={race.total_laps}  ~{race.duration:.0f}s",
    )

    # Send RaceStart event
    start_event = {
        "race_id": race.race_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "race_event",
        "event_data": {"type": "RaceStart", "race_id": race.race_id},
    }
    await _ws_broadcast(race.race_id, start_event)

    tick = 1.2  # seconds per tick
    start_wall = time.time()

    try:
        while time.time() - start_wall < race.duration and not race.cancel_flag:
            await asyncio.sleep(tick)

            race.sim_time += tick * SIM_SPEED
            sim_t = race.sim_time

            # Build telemetry snapshot
            snapshot = {
                "t": round(sim_t, 1),
                "cars": [],
                "events": [],
            }
            for car in race.cars:
                # Estimate which lap each car is on based on sim_time progress
                progress_ratio = min(1.0, sim_t / race.max_sim_time)
                lap = min(
                    _rand_lap_count(race.total_laps),
                    max(1, int(progress_ratio * race.total_laps)),
                )
                lp = progress_ratio * race.total_laps - (lap - 1)
                snapshot["cars"].append(_gen_car_telemetry(car, lap, lp, sim_t))

            race.snapshots.append(snapshot)

            # WebSocket push race_event
            event = {
                "race_id": race.race_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": "race_event",
                "event_data": {"type": "TelemetrySnapshot", "snapshot": snapshot},
            }
            await _ws_broadcast(race.race_id, event)

            log(
                "Y",
                "TICK",
                f"{race.race_id}  sim_t={sim_t:.1f}s  "
                f"cars=[{','.join(f'{c['lap']}L' for c in snapshot['cars'])}]",
            )

        # Race complete
        if race.cancel_flag:
            race.status = "cancelled"
            race.final_result = {
                "session_id": race.race_id,
                "session_type": race.session_type,
                "total_laps": race.total_laps,
                "recording_path": f"./recordings/{race.race_id}",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "duration_sim": race.sim_time,
                "total_frames": len(race.snapshots),
                "teams": [
                    {"team_id": c["team_id"], "team_name": c["team_name"]}
                    for c in race.cars
                ],
                "finish_reason": "admin_stop",
                "final_rankings": [],
            }
            end_event = {
                "race_id": race.race_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": "race_ended",
                "event_data": {"reason": "cancelled", "final_rankings": []},
            }
            log("R", "CANCELLED", race.race_id)
        else:
            race.status = "completed"
            rankings = _gen_final_rankings(race.cars, race.total_laps)
            race.final_result = {
                "session_id": race.race_id,
                "session_type": race.session_type,
                "total_laps": race.total_laps,
                "recording_path": f"./recordings/{race.race_id}",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "duration_sim": round(race.sim_time, 1),
                "total_frames": len(race.snapshots),
                "teams": [
                    {"team_id": c["team_id"], "team_name": c["team_name"]}
                    for c in race.cars
                ],
                "finish_reason": "grace_period_expired",
                "final_rankings": rankings,
            }
            end_event = {
                "race_id": race.race_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": "race_ended",
                "event_data": {
                    "reason": "grace_period_expired",
                    "final_rankings": rankings,
                },
            }
            # Pretty-print rankings
            lines = [
                f"  #{r['rank']} {r['team_name']}  laps={r['laps']}  best={r['best_lap']}s  time={r['total_time']}s"
                for r in rankings
            ]
            log("G", "FINISHED", f"{race.race_id}\n" + "\n".join(lines))

        await _ws_broadcast(race.race_id, end_event)

    except asyncio.CancelledError:
        race.status = "error"
        log("R", "ERROR", f"{race.race_id} simulation cancelled unexpectedly")


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------


async def _ws_broadcast(race_id: str, message: dict) -> None:
    msg = json.dumps(message, ensure_ascii=False)
    async with _lock:
        connections = _ws_connections.get(race_id, set())
    dead: set[WebSocket] = set()
    for ws in connections:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    if dead:
        async with _lock:
            for ws in dead:
                _ws_connections.get(race_id, set()).discard(ws)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "service": "simnode"}


@app.post("/race/create", response_model=RaceCreateResponse)
async def create_race(body: RaceCreateRequest):
    async with _lock:
        if body.race_id in _race_store:
            raise HTTPException(status_code=409, detail=f"比赛ID已存在: {body.race_id}")

        race = MockRace(
            race_id=body.race_id,
            session_type=body.session_type,
            total_laps=body.total_laps,
            cars=[c.model_dump() for c in body.cars],
            duration=random.uniform(*DURATION_RANGE),
        )
        _race_store[body.race_id] = race
        if body.race_id not in _ws_connections:
            _ws_connections[body.race_id] = set()

    log(
        "C",
        "CREATE",
        f"{body.race_id}  type={body.session_type}  cars={len(body.cars)}  laps={body.total_laps}",
    )

    # Start background simulation
    asyncio.create_task(_run_race_simulation(race))

    host = os.getenv("MOCK_HOST", "localhost:8001")
    return RaceCreateResponse(
        status="started",
        race_id=body.race_id,
        stream_ws_url=f"ws://{host}/race/{body.race_id}/stream",
    )


@app.get("/race/{race_id}/status")
async def get_race_status(race_id: str):
    race = _race_store.get(race_id)
    if race is None:
        raise HTTPException(status_code=404, detail=f"比赛未找到: {race_id}")
    return {"race_id": race_id, "status": race.status}


@app.get("/race/{race_id}/live")
async def get_race_live(race_id: str):
    race = _race_store.get(race_id)
    if race is None:
        raise HTTPException(status_code=404, detail=f"Race not found: {race_id}")

    # Return latest snapshot cars
    cars_live = race.snapshots[-1]["cars"] if race.snapshots else []
    return {
        "race_id": race_id,
        "webots_pid": 12345,  # fake PID
        "sim_time": round(race.sim_time, 1),
        "cars": cars_live,
    }


@app.get("/race/{race_id}/result")
async def get_race_result(race_id: str):
    race = _race_store.get(race_id)
    if race is None:
        raise HTTPException(status_code=404, detail=f"比赛未找到: {race_id}")
    if race.status != "completed":
        raise HTTPException(
            status_code=425,
            detail=f"比赛尚未完成，当前状态: {race.status}",
        )
    return race.final_result


@app.get("/race/{race_id}/frame")
async def get_race_frame(race_id: str):
    if race_id not in _race_store:
        raise HTTPException(status_code=404, detail=f"Race not found: {race_id}")
    return Response(
        content=_get_frame_jpeg(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/race/{race_id}/cancel")
async def cancel_race(race_id: str):
    race = _race_store.get(race_id)
    if race is None:
        raise HTTPException(status_code=404, detail=f"比赛未找到或已结束: {race_id}")
    race.cancel_flag = True
    log("M", "CANCEL", race_id)
    return {"status": "cancelled", "race_id": race_id}


@app.get("/races")
async def list_races():
    return [{"race_id": rid, "status": r.status} for rid, r in _race_store.items()]


@app.websocket("/race/{race_id}/stream")
async def stream_race(websocket: WebSocket, race_id: str):
    await websocket.accept()

    async with _lock:
        if race_id not in _ws_connections:
            _ws_connections[race_id] = set()
        _ws_connections[race_id].add(websocket)

    log("B", "WS OPEN", race_id)

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
        log("B", "WS CLOSE", race_id)
    finally:
        async with _lock:
            _ws_connections.get(race_id, set()).discard(websocket)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Mock SimNode")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    print(f"{C['G']}╔══════════════════════════════════════╗{C['X']}")
    print(f"{C['G']}║   Mock SimNode — 模拟仿真服务器      ║{C['X']}")
    print(f"{C['G']}╠══════════════════════════════════════╣{C['X']}")
    print(f"{C['G']}║  端口: {args.port:<4}                       ║{C['X']}")
    print(
        f"{C['G']}║  比赛时长: {DURATION_RANGE[0]}-{DURATION_RANGE[1]}s (随机)              ║{C['X']}"
    )
    print(f"{C['G']}║  模拟倍率: {SIM_SPEED:.1f}x                     ║{C['X']}")
    print(f"{C['G']}╚══════════════════════════════════════╝{C['X']}")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

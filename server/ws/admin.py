"""
Admin WebSocket endpoint.

ws://0.0.0.0:8000/ws/admin

- On connect: immediately sends the current state for every zone.
- Broadcasts state changes with zone_id so the frontend can filter.
- Heartbeat is driven externally by app.py's lifespan task.
- Incoming messages from clients are silently ignored (keep-alive only).
"""

import json
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

_DEFAULT_ZONE_MSG = {
    "type":            "sim_status",
    "zone_id":         "default",
    "state":           "idle",
    "session_id":      None,
    "webots_pid":      None,
    "sim_time_approx": 0,
    "recording_path":  None,
}


class AdminConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        # Per-zone last message cache; also keeps backward-compat _last_msg alias
        self._last_msg_per_zone: dict[str, dict] = {}

    @property
    def _last_msg(self) -> dict:
        """Backward-compat: return the 'default' zone last message."""
        return self._last_msg_per_zone.get("default", dict(_DEFAULT_ZONE_MSG))

    @_last_msg.setter
    def _last_msg(self, value: dict) -> None:
        zone_id = value.get("zone_id", "default")
        self._last_msg_per_zone[zone_id] = value

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        # Send current state for every known zone so the client is not blind
        if self._last_msg_per_zone:
            for msg in self._last_msg_per_zone.values():
                try:
                    await ws.send_json(msg)
                except Exception:
                    break
        else:
            await ws.send_json(dict(_DEFAULT_ZONE_MSG))

    def disconnect(self, ws: WebSocket) -> None:
        try:
            self.active.remove(ws)
        except ValueError:
            pass

    async def broadcast(self, msg: dict) -> None:
        zone_id = msg.get("zone_id", "default")
        self._last_msg_per_zone[zone_id] = msg
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Module-level singleton used by both the WebSocket endpoint and admin REST routes
manager = AdminConnectionManager()


async def broadcast_state(
    state:           str,
    zone_id:         str           = "default",
    session_id:      Optional[str] = None,
    session_type:    Optional[str] = None,
    webots_pid:      Optional[int] = None,
    sim_time_approx: int           = 0,
    recording_path:  Optional[str] = None,
) -> None:
    """Convenience wrapper called by admin REST handlers and heartbeat loop."""
    await manager.broadcast(
        {
            "type":            "sim_status",
            "zone_id":         zone_id,
            "state":           state,
            "session_id":      session_id,
            "session_type":    session_type,
            "webots_pid":      webots_pid,
            "sim_time_approx": sim_time_approx,
            "recording_path":  recording_path,
        }
    )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

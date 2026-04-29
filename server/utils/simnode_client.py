"""
utils/simnode_client.py — Sim Node HTTP 客户端

Backend 通过此模块调用 Sim Node 的 REST API，
相当于 Avalon 中 blueprints/ 直接调用 BattleManager 的 Python 方法，
但这里改为网络调用（Sim Node 是独立服务，部署在 Linux 服务器）。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from server.config.config import Config

logger = logging.getLogger(__name__)

SIMNODE_URL = Config.get("SIMNODE_URL", "http://localhost:8001")


def _url(path: str) -> str:
    return f"{SIMNODE_URL.rstrip('/')}{path}"


# ---------------------------------------------------------------------------
# 启动比赛  ↔  BattleManager.start_battle()
# ---------------------------------------------------------------------------

def start_race(
    race_id:      str,
    session_type: str,
    total_laps:   int,
    cars:         List[Dict[str, Any]],
    timeout:      int = 10,
) -> Dict[str, Any]:
    """
    调用 POST /race/create，返回响应（含 stream_ws_url）。
    失败时抛出 RuntimeError。
    """
    payload = {
        "race_id":      race_id,
        "session_type": session_type,
        "total_laps":   total_laps,
        "cars":         cars,
    }
    try:
        resp = httpx.post(_url("/race/create"), json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Sim Node 拒绝创建比赛: {e.response.status_code} {e.response.text}")
    except httpx.RequestError as e:
        raise RuntimeError(f"无法连接 Sim Node ({SIMNODE_URL}): {e}")


# ---------------------------------------------------------------------------
# 取消比赛  ↔  BattleManager.cancel_battle()
# ---------------------------------------------------------------------------

def cancel_race(race_id: str, timeout: int = 40) -> bool:
    """Send cancel to simnode and wait for it to finish (graceful stop takes up to 35 s)."""
    try:
        resp = httpx.post(_url(f"/race/{race_id}/cancel"), timeout=timeout)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"取消比赛 {race_id} 失败: {e}")
        return False


# ---------------------------------------------------------------------------
# 查询状态  ↔  BattleManager.get_battle_status()
# ---------------------------------------------------------------------------

def get_race_status(race_id: str, timeout: int = 5) -> Optional[str]:
    try:
        resp = httpx.get(_url(f"/race/{race_id}/status"), timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("status")
    except Exception as e:
        logger.warning(f"查询比赛状态失败 ({race_id}): {e}")
        return None


# ---------------------------------------------------------------------------
# 查询结果  ↔  BattleManager.get_battle_result()
# ---------------------------------------------------------------------------

def get_race_result(race_id: str, timeout: int = 5) -> Optional[Dict]:
    try:
        resp = httpx.get(_url(f"/race/{race_id}/result"), timeout=timeout)
        if resp.status_code in (404, 425):
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"查询比赛结果失败 ({race_id}): {e}")
        return None


# ---------------------------------------------------------------------------
# 列出所有比赛  ↔  BattleManager.get_all_battles()
# ---------------------------------------------------------------------------

def get_race_live_info(race_id: str, timeout: int = 3) -> Optional[Dict]:
    """Return real-time info: webots_pid, sim_time, cars (latest telemetry frame)."""
    try:
        resp = httpx.get(_url(f"/race/{race_id}/live"), timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"获取比赛实时信息失败 ({race_id}): {e}")
        return None


def list_races(timeout: int = 5) -> List[Tuple[str, str]]:
    try:
        resp = httpx.get(_url("/races"), timeout=timeout)
        resp.raise_for_status()
        return [(r["race_id"], r["status"]) for r in resp.json()]
    except Exception as e:
        logger.warning(f"列出比赛失败: {e}")
        return []

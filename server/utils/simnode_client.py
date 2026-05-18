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

SIMNODE_URL = Config.get("SIMNODE_URL", "http://localhost:5000")

# 使用支持并发的异步客户端（线程安全），替代原来的同步 Client
# 同步 Client 在多线程 asyncio.to_thread 场景下连接池行为不可靠（尤其 Windows）
_async_client: Optional[httpx.AsyncClient] = None


def _get_async_client() -> httpx.AsyncClient:
    """延迟初始化异步客户端，复用连接池。"""
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            proxy=None,
            trust_env=False,
            timeout=httpx.Timeout(3.0, connect=1.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _async_client


def _url(path: str) -> str:
    return f"{SIMNODE_URL.rstrip('/')}{path}"


# ---------------------------------------------------------------------------
# 启动比赛  ↔  BattleManager.start_battle()
# ---------------------------------------------------------------------------


def start_race(
    race_id: str,
    session_type: str,
    total_laps: int,
    cars: List[Dict[str, Any]],
    world: str = "complex",
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    调用 POST /race/create，返回响应（含 stream_ws_url）。
    失败时抛出 RuntimeError。
    """
    payload = {
        "race_id": race_id,
        "session_type": session_type,
        "total_laps": total_laps,
        "cars": cars,
        "world": world,
    }
    # start_race 是冷启动路径，用同步客户端避免事件循环依赖
    try:
        with httpx.Client(proxy=None, trust_env=False, timeout=timeout) as client:
            resp = client.post(_url("/race/create"), json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Sim Node 拒绝创建比赛: {e.response.status_code} {e.response.text}"
        )
    except httpx.RequestError as e:
        raise RuntimeError(f"无法连接 Sim Node ({SIMNODE_URL}): {e}")


# ---------------------------------------------------------------------------
# 取消比赛  ↔  BattleManager.cancel_battle()
# ---------------------------------------------------------------------------


def cancel_race(race_id: str, timeout: int = 40) -> bool:
    """Send cancel to simnode and wait for it to finish (graceful stop takes up to 35 s)."""
    try:
        with httpx.Client(proxy=None, trust_env=False, timeout=timeout) as client:
            resp = client.post(_url(f"/race/{race_id}/cancel"))
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"取消比赛 {race_id} 失败: {e}")
        return False


# ---------------------------------------------------------------------------
# 查询状态  ↔  BattleManager.get_battle_status()
# ---------------------------------------------------------------------------


def get_race_status(race_id: str, timeout: int = 5) -> Optional[str]:
    try:
        with httpx.Client(proxy=None, trust_env=False, timeout=timeout) as client:
            resp = client.get(_url(f"/race/{race_id}/status"))
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
        with httpx.Client(proxy=None, trust_env=False, timeout=timeout) as client:
            resp = client.get(_url(f"/race/{race_id}/result"))
            if resp.status_code in (404, 425):
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"查询比赛结果失败 ({race_id}): {e}")
        return None


# ---------------------------------------------------------------------------
# 热路径：获取比赛实时信息（异步版，用于 _sim_live_loop）
# ---------------------------------------------------------------------------


async def get_race_live_info_async(
    race_id: str, timeout: float = 1.5
) -> Optional[Dict]:
    """异步版：Return real-time info from simnode. 用于热路径避免阻塞线程池。"""
    try:
        client = _get_async_client()
        resp = await client.get(_url(f"/race/{race_id}/live"), timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"获取比赛实时信息失败 ({race_id}): {e}")
        return None


# 同步版（向后兼容，用于非 async 上下文）
def get_race_live_info(race_id: str, timeout: int = 3) -> Optional[Dict]:
    """Return real-time info: webots_pid, sim_time, cars (latest telemetry frame)."""
    try:
        with httpx.Client(proxy=None, trust_env=False, timeout=timeout) as client:
            resp = client.get(_url(f"/race/{race_id}/live"))
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"获取比赛实时信息失败 ({race_id}): {e}")
        return None


# ---------------------------------------------------------------------------
# 热路径：获取俯视摄像头帧（异步版，复用连接池）
# ---------------------------------------------------------------------------


async def get_race_frame_async(race_id: str, timeout: float = 1.5) -> Optional[bytes]:
    """异步版：Return overhead camera JPEG bytes. 复用全局连接池。"""
    try:
        client = _get_async_client()
        resp = await client.get(_url(f"/race/{race_id}/frame"), timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


def list_races(timeout: int = 5) -> List[Tuple[str, str]]:
    try:
        with httpx.Client(proxy=None, trust_env=False, timeout=timeout) as client:
            resp = client.get(_url("/races"))
            resp.raise_for_status()
            return [(r["race_id"], r["status"]) for r in resp.json()]
    except Exception as e:
        logger.warning(f"列出比赛失败: {e}")
        return []

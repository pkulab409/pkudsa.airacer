"""
services/race_service.py — 比赛相关业务逻辑，对应 Avalon 的 services/battle_service.py

职责：处理比赛结束后的数据库写入、测试报告处理等，
使 blueprints/ 的路由函数保持简洁（与 Avalon 的分层一致）。
"""

import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from server.database import action

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 处理 Sim Node 推送的 race_ended 事件
# （对应 Avalon battle_service.update_battle_result）
# ---------------------------------------------------------------------------

def on_race_ended(race_id: str, result: Dict[str, Any]) -> None:
    """
    比赛正常结束时，将结果写入数据库。
    由 Backend 的 WebSocket 回调调用（收到 race_ended 消息后）。
    """
    finish_reason   = result.get("finish_reason", "unknown")
    final_rankings  = result.get("final_rankings", [])
    finished_at     = datetime.datetime.now().isoformat()

    try:
        action.update_race_session(
            race_id,
            phase="finished",
            finished_at=finished_at,
            result=result,
        )
    except Exception as e:
        logger.error(f"写入比赛结果失败 ({race_id}): {e}")
        return

    # 按排名写入积分（对应 Avalon GameStats 写入）
    _POINTS_TABLE = {1: 10, 2: 7, 3: 5, 4: 3}
    for entry in final_rankings:
        rank    = entry.get("rank", 99)
        team_id = entry.get("team_id")
        if team_id:
            points = _POINTS_TABLE.get(rank, 1)
            try:
                action.upsert_race_points(race_id, team_id, rank, points)
            except Exception as e:
                logger.warning(f"写入积分失败 ({race_id}, {team_id}): {e}")

    logger.info(f"比赛 {race_id} 结果已写入数据库，原因: {finish_reason}")


# ---------------------------------------------------------------------------
# 处理测试跑完成（对应 Avalon 私有对局记录写入）
# ---------------------------------------------------------------------------

def on_test_run_ended(
    test_run_id: int,
    result: Dict[str, Any],
) -> None:
    """
    测试跑结束后写入 test_runs 表。
    """
    finished_at = datetime.datetime.now().isoformat()
    rankings    = result.get("final_rankings", [])

    laps_completed   = 0
    best_lap_time    = None
    collisions_minor = 0
    collisions_major = 0
    timeout_warnings = 0

    if rankings:
        first = rankings[0]
        laps_completed = first.get("laps_completed", 0)
        if "best_lap_time" in first:
            best_lap_time = first["best_lap_time"]
        elif "lap_times" in first:
            lap_times = [t for t in first.get("lap_times", []) if t is not None]
            best_lap_time = min(lap_times) if lap_times else None

    # 从 events 中提取碰撞/超时计数
    for event in result.get("events", []):
        etype = event.get("event_type") or event.get("type")
        if etype == "Collision":
            sev = event.get("event_data", {}).get("severity", "minor")
            if sev == "major":
                collisions_major += 1
            else:
                collisions_minor += 1
        elif etype == "TimeoutWarn":
            timeout_warnings += 1

    try:
        action.update_test_run(
            test_run_id,
            status="done",
            finished_at=finished_at,
            laps_completed=laps_completed,
            best_lap_time=best_lap_time,
            collisions_minor=collisions_minor,
            collisions_major=collisions_major,
            timeout_warnings=timeout_warnings,
            finish_reason=result.get("finish_reason", "unknown"),
        )
    except Exception as e:
        logger.error(f"写入测试报告失败 (test_run_id={test_run_id}): {e}")

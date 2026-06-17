"""
services/race_service.py — 比赛相关业务逻辑，对应 Avalon 的 services/battle_service.py

职责：处理比赛结束后的数据库写入、测试报告处理等，
使 blueprints/ 的路由函数保持简洁（与 Avalon 的分层一致）。
"""

import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from server.config.config import DB_PATH
from server.database import action
from server.database.models import get_db

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
    finish_reason = result.get("finish_reason", "unknown")
    final_rankings = result.get("final_rankings", [])
    finished_at = datetime.datetime.now().isoformat()

    _POINTS_TABLE = {1: 10, 2: 7, 3: 5, 4: 3}

    try:
        with get_db(DB_PATH) as conn:
            action.update_race_session(
                conn,
                race_id,
                phase="finished",
                finished_at=finished_at,
                result=result,
            )
            for entry in final_rankings:
                rank = entry.get("rank", 99)
                team_id = entry.get("team_id")
                status = entry.get("status", "")
                if team_id:
                    # 未完赛队伍一律只给 1 分，不按具体排名给分
                    if status == "finished":
                        points = _POINTS_TABLE.get(rank, 1)
                    else:
                        points = 1
                    action.upsert_race_points(conn, race_id, team_id, rank, points)
    except Exception as e:
        logger.error(f"写入比赛结果失败 ({race_id}): {e}")
        return

    logger.info(f"比赛 {race_id} 结果已写入数据库，原因: {finish_reason}")

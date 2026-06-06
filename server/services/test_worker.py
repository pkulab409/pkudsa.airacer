"""
services/test_worker.py — 测试赛事队列消费者

启动后轮询 race 内存队列，逐个调用 Sim Node 执行多车测试赛事，
完成后将结果写入数据库。
"""

import asyncio
import base64
import datetime
import json
import logging
import pathlib
import time as _time

from server.config.config import DB_PATH
from server.database.action import (
    db_get_teams_with_code,
)
from server.database.models import get_db
from server.utils.simnode_client import (
    get_race_result as simnode_get_result,
)
from server.utils.simnode_client import (
    get_race_status as simnode_get_status,
)
from server.utils.simnode_client import (
    start_race as simnode_start_race,
)

logger = logging.getLogger(__name__)

# SDK 官方模板路径（队伍未上传代码时兜底用）
_DEFAULT_CODE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent.parent / "sdk" / "team_controller.py"
)

# 单场比赛最大轮询时间（超过则标记超时），防止 worker 异常导致 DB 永久 running
_POLL_TOTAL_TIMEOUT = 7200.0  # 2 小时


async def _recover_stuck_races() -> list[str]:
    """Backend 启动时恢复 stuck races。

    假设 SimNode 已经重启过（内存清空），
    把 DB 中 running → waiting（重置状态），
    然后返回所有需要重新入队发送给 SimNode 的 race_id 列表。
    """
    from server.database.action import update_race as db_update_race

    try:
        with get_db(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id, status FROM races WHERE status IN ('running', 'waiting')"
            ).fetchall()
    except Exception as e:
        logger.warning(f"恢复 stuck races 查询失败: {e}")
        return []

    if not rows:
        return []

    recovered: list[str] = []
    for row in rows:
        race_id = row["id"]
        cur_status = row["status"]

        if cur_status == "running":
            with get_db(DB_PATH) as conn:
                db_update_race(conn, race_id, status="waiting", started_at=None)
            logger.info(f"race {race_id} 从 running 恢复为 waiting")

        recovered.append(race_id)

    logger.info(
        f"发现 {len(recovered)} 条 stuck race，已全部恢复为 waiting，等待重新发送"
    )
    return recovered


# ---------------------------------------------------------------------------
# 统一 race 类型测试赛事 Worker
# ---------------------------------------------------------------------------


async def _race_event_worker_loop() -> None:
    """主循环：每 2 秒取 race 队列头部，全部发射给 simnode（SimNode 内部排队管理并发）。"""
    from server.blueprints.races import _dequeue_race, _enqueue_race

    # 启动时恢复 stuck races：running→waiting，并重新入队发送给 SimNode
    recovered = await _recover_stuck_races()
    for race_id in recovered:
        _enqueue_race(race_id)
        logger.info(f"race {race_id} 已重新入队")

    running = set()

    while True:
        await asyncio.sleep(2)

        done = {t for t in running if t.done()}
        for t in done:
            if t.exception():
                logger.exception("race worker err: " + str(t.exception()))
            running.discard(t)

        race_id = _dequeue_race()
        if race_id is None:
            continue

        coro = _run_single_race_event(race_id)
        running.add(asyncio.create_task(coro))


async def _run_single_race_event(race_id: str) -> None:
    """执行单个 race 事件（外层兜底异常处理）。"""
    try:
        await _run_single_race_event_impl(race_id)
    except Exception as e:
        logger.exception(f"race 事件未预期异常 (race_id={race_id}): {e}")
        _mark_race_error(race_id, f"unexpected_error: {e}")


async def _run_single_race_event_impl(race_id: str) -> None:
    from server.database.action import get_race as db_get_race
    from server.database.action import update_race as db_update_race

    # 1. 读 race 记录
    with get_db(DB_PATH) as conn:
        race = db_get_race(conn, race_id)
    if race is None:
        logger.warning(f"race 不存在: {race_id}")
        return
    if race["status"] != "waiting":
        logger.warning(f"race {race_id} 状态不是 waiting，跳过: {race['status']}")
        return

    participant_ids = json.loads(race["participant_ids"])
    world_key = race["world_key"]
    total_laps = race["total_laps"]

    # 2. 查参与者代码
    with get_db(DB_PATH) as conn:
        teams_data = db_get_teams_with_code(conn, participant_ids)

    # 3. 构建 cars 列表
    code_cache: dict[str, str] = {}
    cars = []
    for idx, team in enumerate(teams_data):
        cp = team.get("code_path")
        if not cp:
            code_path = _DEFAULT_CODE_PATH
            if not code_path.exists():
                _mark_race_error(race_id, f"default_code_missing")
                return
            code_b64 = base64.b64encode(code_path.read_bytes()).decode()
        else:
            code_path = pathlib.Path(cp)
            if not code_path.exists():
                _mark_race_error(race_id, f"code_file_missing:{team['id']}")
                return
            cpath_str = str(code_path)
            if cpath_str not in code_cache:
                code_cache[cpath_str] = base64.b64encode(
                    code_path.read_bytes()
                ).decode()
            code_b64 = code_cache[cpath_str]
        cars.append(
            {
                "car_slot": f"car_{idx + 1}",
                "team_id": team["id"],
                "team_name": team["name"],
                "code_b64": code_b64,
            }
        )

    # 4. 调用 Sim Node（SimNode 内部管理并发排队，不再拒绝）
    sim_race_id = f"race_{race_id[:8]}"
    try:
        await asyncio.to_thread(
            simnode_start_race,
            sim_race_id,
            "test",
            total_laps,
            cars,
            world=world_key,
        )
    except RuntimeError as exc:
        _mark_race_error(race_id, f"simnode_unreachable: {exc}")
        return

    logger.info(f"测试赛事已提交到 SimNode: {sim_race_id} (race_id={race_id})")

    # 5. 轮询等待完成（SimNode 可能先返回 queued，再变为 running）
    db_running_set = False
    none_strikes = 0
    poll_start = _time.monotonic()
    while True:
        await asyncio.sleep(5)

        # 总超时检查
        if _time.monotonic() - poll_start > _POLL_TOTAL_TIMEOUT:
            _mark_race_error(race_id, "poll_timeout")
            return

        status = await asyncio.to_thread(simnode_get_status, sim_race_id)

        if status is None:
            none_strikes += 1
            if none_strikes >= 3:
                _mark_race_error(race_id, "simnode_lost")
                return
            continue

        none_strikes = 0

        # 当 SimNode 状态变为 running 时，更新 DB
        if status == "running" and not db_running_set:
            db_running_set = True
            now = datetime.datetime.now().isoformat()
            try:
                with get_db(DB_PATH) as conn:
                    db_update_race(conn, race_id, status="running", started_at=now)
                logger.info(f"测试赛事开始执行 (SimNode 确认): {sim_race_id}")
            except Exception as e:
                logger.warning(f"更新 race running 状态失败: {e}")

        if status == "completed":
            result = await asyncio.to_thread(simnode_get_result, sim_race_id)
            if result:
                finished_at = datetime.datetime.now().isoformat()
                with get_db(DB_PATH) as conn:
                    db_update_race(
                        conn,
                        race_id,
                        status="done",
                        finished_at=finished_at,
                        finish_reason=result.get("finish_reason", "unknown"),
                        result=json.dumps(result, ensure_ascii=False),
                    )
                logger.info(f"测试赛事完成: {sim_race_id} (race_id={race_id})")
            else:
                _mark_race_error(race_id, "no_result_from_simnode")
            return

        if status in ("error", "cancelled"):
            _mark_race_error(race_id, f"simnode_{status}")
            return


def _mark_race_error(race_id: str, reason: str) -> None:
    logger.warning(f"测试赛事失败 (race_id={race_id}): {reason}")
    try:
        with get_db(DB_PATH) as conn:
            from server.database.action import update_race as db_update_race

            db_update_race(conn, race_id, status="error", finish_reason=reason)
    except Exception:
        logger.exception(f"写入错误状态失败 (race_id={race_id})")

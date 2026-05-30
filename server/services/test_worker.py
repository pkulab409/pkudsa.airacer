"""
services/test_worker.py — 测试队列消费者

启动后轮询内存测试队列，逐个调用 Sim Node 执行单车辆测试赛，
完成后通过 race_service.on_test_run_ended() 写入结果。
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
    db_get_submission_by_id,
    db_get_team_secure,
    db_get_teams_with_code,
    update_test_run,
)
from server.database.models import get_db
from server.services.race_service import on_test_run_ended
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

# ---------------------------------------------------------------------------
# 背压重试：simnode 并发槽满时等待而不要立刻失败
# ---------------------------------------------------------------------------

_RETRY_BACKOFF_START = 2.0
_RETRY_BACKOFF_MAX = 60.0
_RETRY_TOTAL_TIMEOUT = 600.0

# 单场比赛最大轮询时间（超过则标记超时），防止 worker 异常导致 DB 永久 running
_POLL_TOTAL_TIMEOUT = 900.0  # 15 分钟


async def _start_race_with_retry(
    race_id: str,
    session_type: str,
    total_laps: int,
    cars: list,
    world: str = "complex",
    slot_name: str = "",
) -> None:
    waited = 0.0
    delay = _RETRY_BACKOFF_START

    while True:
        try:
            await asyncio.to_thread(
                simnode_start_race, race_id, session_type, total_laps, cars, world
            )
            return
        except RuntimeError as exc:
            msg = str(exc)
            if "409" in msg or "并发" in msg:
                if waited >= _RETRY_TOTAL_TIMEOUT:
                    raise RuntimeError(
                        f"SimNode 持续繁忙，已等待 {waited:.0f}s，放弃: {msg}"
                    ) from exc
                logger.info(
                    "SimNode 并发已满，%s 秒后重试 (已等待 %.0fs, slot=%s)",
                    delay,
                    waited,
                    slot_name,
                )
                await asyncio.sleep(delay)
                waited += delay
                delay = min(delay * 2, _RETRY_BACKOFF_MAX)
                continue
            raise


async def _test_worker_loop() -> None:
    """主循环：每 2 秒取队列头部任务，全部发射给 simnode，由其背压排队。"""
    from server.blueprints.submission import dequeue_test

    # 启动时恢复 stuck test_runs
    await _recover_stuck_test_runs()

    running: set[asyncio.Task] = set()

    while True:
        await asyncio.sleep(2)

        # 清理已完成的任务
        done = {t for t in running if t.done()}
        for t in done:
            if t.exception():
                logger.exception(f"测试 worker 异常: {t.exception()}")
            running.discard(t)

        task = dequeue_test()
        if task is None:
            continue

        coro = _run_single_test(task)
        running.add(asyncio.create_task(coro))


async def _run_single_test(task: dict) -> None:
    """执行单个测试：读代码 → 调 Sim Node → 轮询结果 → 写库。"""
    submission_id = task["submission_id"]
    test_run_id = task["test_run_id"]
    team_id = task["team_id"]

    # 用最外层 try/except 确保任何未预期异常都会更新 DB 状态
    try:
        await _run_single_test_impl(task)
    except Exception as e:
        logger.exception(f"测试赛未预期异常 (test_run_id={test_run_id}): {e}")
        _mark_error(test_run_id, f"unexpected_error: {e}")


async def _run_single_test_impl(task: dict) -> None:
    submission_id = task["submission_id"]
    test_run_id = task["test_run_id"]
    team_id = task["team_id"]

    # 1. 查 DB 获取提交和队伍信息
    with get_db(DB_PATH) as conn:
        sub = db_get_submission_by_id(conn, submission_id)
        team = db_get_team_secure(conn, team_id)

    if sub is None:
        _mark_error(test_run_id, "submission_not_found")
        return
    if team is None:
        _mark_error(test_run_id, "team_not_found")
        return

    code_path = pathlib.Path(sub["code_path"])
    if not code_path.exists():
        _mark_error(test_run_id, "code_file_missing")
        return

    # 2. 构建单车 cars 列表
    code_b64 = base64.b64encode(code_path.read_bytes()).decode()
    cars = [
        {
            "car_slot": "car_1",
            "team_id": team["id"],
            "team_name": team["name"],
            "code_b64": code_b64,
        }
    ]

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    race_id = f"test_{team_id}_{task['slot_name']}_{timestamp}"

    # 3. 标记 test_run 为 running
    now = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        update_test_run(conn, test_run_id, status="running", started_at=now)

    # 4. 调用 Sim Node（并发满时自动重试等待）
    world_key = task.get("world_key", "complex")
    try:
        await _start_race_with_retry(
            race_id,
            "test",
            3,
            cars,
            world=world_key,
            slot_name=task.get("slot_name", ""),
        )
    except RuntimeError as exc:
        _mark_error(test_run_id, f"simnode_unreachable: {exc}")
        return

    logger.info(f"测试赛已启动: {race_id}")

    # 5. 轮询等待完成（带总超时保护）
    none_strikes = 0
    poll_start = _time.monotonic()
    while True:
        await asyncio.sleep(5)

        # 总超时检查：防止 worker 异常导致 DB 永久 "running"
        if _time.monotonic() - poll_start > _POLL_TOTAL_TIMEOUT:
            _mark_error(test_run_id, "poll_timeout")
            return

        status = await asyncio.to_thread(simnode_get_status, race_id)

        if status is None:
            none_strikes += 1
            if none_strikes >= 3:
                _mark_error(test_run_id, "simnode_lost")
                return
            continue

        none_strikes = 0

        if status == "completed":
            result = await asyncio.to_thread(simnode_get_result, race_id)
            if result:
                on_test_run_ended(test_run_id, result)
                logger.info(f"测试赛完成: {race_id}")
            else:
                _mark_error(test_run_id, "no_result_from_simnode")
            return

        if status in ("error", "cancelled"):
            _mark_error(test_run_id, f"simnode_{status}")
            return


def _mark_error(test_run_id: int, reason: str) -> None:
    logger.warning(f"测试赛失败 (test_run_id={test_run_id}): {reason}")
    try:
        with get_db(DB_PATH) as conn:
            update_test_run(conn, test_run_id, status="error", finish_reason=reason)
    except Exception:
        logger.exception(f"写入错误状态失败 (test_run_id={test_run_id})")


# ---------------------------------------------------------------------------
# 启动恢复：扫描所有 status='running' 的记录，与 simnode 同步
# ---------------------------------------------------------------------------


async def _recover_stuck_test_runs() -> None:
    """Backend 启动时：将 DB 中状态为 running 的 test_runs 与 simnode 同步。"""
    try:
        with get_db(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT tr.id, tr.submission_id, s.team_id "
                "FROM test_runs tr "
                "JOIN submissions s ON tr.submission_id = s.id "
                "WHERE tr.status = 'running'"
            ).fetchall()
    except Exception as e:
        logger.warning(f"恢复 stuck test_runs 查询失败: {e}")
        return

    if not rows:
        return

    logger.info(f"发现 {len(rows)} 条 running 状态的 test_run，正在恢复...")
    for row in rows:
        test_run_id = row["id"]
        # 直接标记为 error（simnode 侧的 race 已随进程生命周期结束）
        # 更健壮的方案是尝试查询 simnode，但 simnode 重启后内存记录丢失
        _mark_error(test_run_id, "recovered_after_restart")
        logger.info(f"test_run {test_run_id} 已恢复为 error (recovered_after_restart)")


async def _recover_stuck_races() -> None:
    """Backend 启动时：将 DB 中状态为 running 的 races 与 simnode 同步。"""
    try:
        with get_db(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id FROM races WHERE status = 'running'"
            ).fetchall()
    except Exception as e:
        logger.warning(f"恢复 stuck races 查询失败: {e}")
        return

    if not rows:
        return

    from server.database.action import update_race as db_update_race

    logger.info(f"发现 {len(rows)} 条 running 状态的 race，正在恢复...")
    for row in rows:
        race_id = row["id"]
        try:
            with get_db(DB_PATH) as conn:
                db_update_race(
                    conn, race_id, status="error",
                    finish_reason="recovered_after_restart",
                )
            logger.info(f"race {race_id} 已恢复为 error (recovered_after_restart)")
        except Exception as e:
            logger.warning(f"恢复 race {race_id} 失败: {e}")


# ---------------------------------------------------------------------------
# 统一 race 类型测试赛事 Worker
# ---------------------------------------------------------------------------


async def _race_event_worker_loop() -> None:
    """主循环：每 2 秒取 race 队列头部，全部发射给 simnode。"""
    # 启动时恢复 stuck races
    await _recover_stuck_races()

    running = set()

    while True:
        await asyncio.sleep(2)

        done = {t for t in running if t.done()}
        for t in done:
            if t.exception():
                logger.exception('race worker err: ' + str(t.exception()))
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

    # 4. 标记 running
    sim_race_id = f"race_{race_id[:8]}"
    now = datetime.datetime.now().isoformat()
    with get_db(DB_PATH) as conn:
        db_update_race(conn, race_id, status="running", started_at=now)

    # 5. 调 Sim Node（并发满时自动重试等待）
    try:
        await _start_race_with_retry(
            sim_race_id,
            "test",
            total_laps,
            cars,
            world=world_key,
            slot_name=f"race_{race_id[:6]}",
        )
    except RuntimeError as exc:
        _mark_race_error(race_id, f"simnode_unreachable: {exc}")
        return

    logger.info(f"测试赛事已启动: {sim_race_id} (race_id={race_id})")

    # 6. 轮询等待完成（带总超时保护）
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

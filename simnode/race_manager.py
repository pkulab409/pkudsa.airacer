import logging
import threading
import time as _time
from typing import Any, Callable, Dict, List, Optional, Tuple

from simnode.race_runner import RaceRunner
from simnode.telemetry_observer import TelemetryObserver
from simnode.config.config import Config

logger = logging.getLogger(__name__)

# 已结束比赛在内存中保留的最长时间（秒），超时自动清理
_RACE_RECORD_TTL = 300  # 5 分钟，足够前端轮询结果


class _RaceRecord:
    def __init__(
        self,
        race_id: str,
        runner:  "RaceRunner | None",
        observer: "TelemetryObserver | None",
        thread:  "threading.Thread | None",
    ):
        self.race_id  = race_id
        self.runner   = runner
        self.observer = observer
        self.thread   = thread
        self.status   = "waiting"   # queued → waiting → running → completed | error | cancelled
        self.result:  Optional[Dict[str, Any]] = None
        self.error:   Optional[str] = None
        self._finished_at: Optional[float] = None  # 比赛结束时的时间戳


class RaceManager:
    """单例比赛管理器，管理所有比赛的生命周期。"""

    _instance: Optional["RaceManager"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "RaceManager":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._races: Dict[str, _RaceRecord] = {}
                    inst._lock  = threading.Lock()
                    inst._pending_queue: list[dict] = []
                    cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------

    def start_race(
        self,
        race_id:      str,
        session_type: str,
        total_laps:   int,
        cars:         List[Dict[str, Any]],
        ws_push_callback: Optional[Callable[[dict], None]] = None,
    ) -> str:
        """创建并启动一场比赛，返回 race_id。
        如果并发已满，自动加入等待队列，等有槽位时自动启动。"""
        # 先清理已结束的过期记录，释放文件描述符
        self.cleanup_stale_races()

        max_concurrent = Config.get("MAX_CONCURRENT_RACES", 4)
        with self._lock:
            if race_id in self._races:
                raise ValueError(f"race_id 已存在: {race_id}")
            running_count = sum(
                1 for r in self._races.values() if r.status == "running"
            )
            if running_count >= max_concurrent:
                # 并发已满：加入等待队列，不拒绝
                self._pending_queue.append(dict(
                    race_id=race_id,
                    session_type=session_type,
                    total_laps=total_laps,
                    cars=cars,
                    ws_push_callback=ws_push_callback,
                ))
                record = _RaceRecord(race_id=race_id, runner=None, observer=None, thread=None)
                record.status = "queued"
                self._races[race_id] = record
                logger.info(
                    f"比赛 {race_id} 已加入等待队列 (队列长度 {len(self._pending_queue)}, "
                    f"当前并发 {running_count}/{max_concurrent})"
                )
                return race_id

        return self._do_start_race(race_id, session_type, total_laps, cars, ws_push_callback)

    def _do_start_race(
        self,
        race_id:      str,
        session_type: str,
        total_laps:   int,
        cars:         List[Dict[str, Any]],
        ws_push_callback: Optional[Callable[[dict], None]] = None,
    ) -> str:
        """实际启动比赛（创建 runner/observer/线程）。"""
        recordings_dir = Config.get("RECORDINGS_DIR", "./recordings")
        observer = TelemetryObserver(
            race_id=race_id,
            recordings_dir=recordings_dir,
            ws_push_callback=ws_push_callback,
        )

        runner = RaceRunner(
            race_id=race_id,
            session_type=session_type,
            total_laps=total_laps,
            cars=cars,
            observer=observer,
        )

        def _execute():
            record = self._races.get(race_id)
            if record is None:
                return
            try:
                record.status = "running"
                logger.info(f"比赛 {race_id} 开始执行")
                result = runner.run_race()
                with self._lock:
                    record.status = "completed"
                    record.result = result
                    record._finished_at = _time.time()
                logger.info(f"比赛 {race_id} 结束: {result.get('finish_reason')}")
            except Exception as e:
                logger.exception(f"比赛 {race_id} 异常: {e}")
                with self._lock:
                    record.status = "error"
                    record.error  = str(e)
                    record._finished_at = _time.time()
                try:
                    observer.make_snapshot("race_error", {
                        "error_type": "runner_exception",
                        "message":    str(e),
                    })
                except Exception:
                    pass
            finally:
                # 比赛结束后尝试启动等待队列中的下一场
                self._try_start_pending()

        thread = threading.Thread(target=_execute, daemon=True, name=f"race-{race_id}")

        with self._lock:
            record = self._races.get(race_id)
            if record is None:
                record = _RaceRecord(race_id=race_id, runner=runner, observer=observer, thread=thread)
            else:
                # 之前在排队，补全 runner/observer/thread
                record.runner   = runner
                record.observer = observer
                record.thread   = thread
                record.status   = "waiting"  # 线程即将设置 running
            self._races[race_id] = record

        thread.start()
        logger.info(f"已启动比赛线程: {race_id}")
        return race_id

    def _try_start_pending(self) -> None:
        """比赛结束后调用：检查等待队列，有槽位时启动最早排队的比赛。"""
        max_concurrent = Config.get("MAX_CONCURRENT_RACES", 4)
        with self._lock:
            if not self._pending_queue:
                return
            running_count = sum(
                1 for r in self._races.values() if r.status == "running"
            )
            if running_count >= max_concurrent:
                return
            params = self._pending_queue.pop(0)

        race_id = params["race_id"]
        logger.info(
            f"从等待队列启动比赛: {race_id} "
            f"(剩余队列长度 {len(self._pending_queue)})"
        )
        try:
            self._do_start_race(**params)
        except Exception as e:
            logger.exception(f"从等待队列启动比赛 {race_id} 失败: {e}")
            with self._lock:
                record = self._races.get(race_id)
                if record:
                    record.status = "error"
                    record.error  = f"queue_start_failed: {e}"
                    record._finished_at = _time.time()

    # ------------------------------------------------------------------

    def get_race_status(self, race_id: str) -> Optional[str]:
        """返回比赛状态：queued / waiting / running / completed / error / cancelled / None"""
        with self._lock:
            rec = self._races.get(race_id)
        return rec.status if rec else None

    def get_race_result(self, race_id: str) -> Optional[Dict[str, Any]]:
        """返回已完成比赛的结果，仅 status == 'completed' 时有值。"""
        with self._lock:
            rec = self._races.get(race_id)
        if rec and rec.status == "completed":
            return rec.result
        return None

    def get_all_races(self) -> List[Tuple[str, str]]:
        """列出所有比赛及状态，返回 [(race_id, status), ...]"""
        with self._lock:
            return [(race_id, rec.status) for race_id, rec in self._races.items()]

    # ------------------------------------------------------------------

    def cancel_race(self, race_id: str) -> bool:
        """终止比赛。排队中的直接取消，运行中的优雅停止。"""
        with self._lock:
            rec = self._races.get(race_id)

        if rec is None:
            return False

        if rec.status == "queued":
            # 从等待队列中移除
            with self._lock:
                self._pending_queue = [
                    p for p in self._pending_queue if p["race_id"] != race_id
                ]
                rec.status = "cancelled"
                rec._finished_at = _time.time()
            logger.info(f"比赛 {race_id} 已从等待队列取消")
            return True

        if rec.status not in ("waiting", "running"):
            return False

        try:
            rec.runner.graceful_stop()
        except Exception as e:
            logger.warning(f"优雅停止 {race_id} 时异常: {e}")

        # Wait for the runner thread so metadata.json is written before we return
        if rec.thread and rec.thread.is_alive():
            rec.thread.join(timeout=20.0)

        with self._lock:
            if rec.status not in ("completed", "error"):
                rec.status = "cancelled"
                rec._finished_at = _time.time()
                try:
                    rec.observer.make_snapshot("race_ended", {
                        "reason":         "cancelled",
                        "final_rankings": [],
                    })
                except Exception:
                    pass

        logger.info(f"比赛 {race_id} 已停止 (status={rec.status})")
        return True

    # ------------------------------------------------------------------

    def get_webots_pid(self, race_id: str) -> Optional[int]:
        with self._lock:
            rec = self._races.get(race_id)
        if rec is None or rec.runner is None:
            return None
        proc = rec.runner._webots_proc
        if proc and proc.poll() is None:
            return proc.pid
        return None

    def get_stream_url(self, race_id: str, host: str = None) -> str:
        h = host or Config.get("SIMNODE_HOST", "localhost:5000")
        return f"ws://{h}/race/{race_id}/stream"

    # ------------------------------------------------------------------

    def cleanup_stale_races(self):
        """清理已结束的比赛记录。"""
        with self._lock:
            now = _time.time()
            for race_id, record in list(self._races.items()):
                if record._finished_at and (now - record._finished_at) > _RACE_RECORD_TTL:
                    del self._races[race_id]
                    logger.info(f"已清理过期比赛记录: {race_id}")

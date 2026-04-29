import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from simnode.race_runner import RaceRunner
from simnode.telemetry_observer import TelemetryObserver
from simnode.config.config import Config

logger = logging.getLogger(__name__)


class _RaceRecord:
    def __init__(
        self,
        race_id: str,
        runner:  "RaceRunner",
        observer: TelemetryObserver,
        thread:  threading.Thread,
    ):
        self.race_id  = race_id
        self.runner   = runner
        self.observer = observer
        self.thread   = thread
        self.status   = "waiting"   # waiting → running → completed | error | cancelled
        self.result:  Optional[Dict[str, Any]] = None
        self.error:   Optional[str] = None


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
        """创建并启动一场比赛，返回 race_id。"""
        with self._lock:
            if race_id in self._races:
                raise ValueError(f"race_id 已存在: {race_id}")

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
                logger.info(f"比赛 {race_id} 结束: {result.get('finish_reason')}")
            except Exception as e:
                logger.exception(f"比赛 {race_id} 异常: {e}")
                with self._lock:
                    record.status = "error"
                    record.error  = str(e)
                try:
                    observer.make_snapshot("race_error", {
                        "error_type": "runner_exception",
                        "message":    str(e),
                    })
                except Exception:
                    pass

        thread = threading.Thread(target=_execute, daemon=True, name=f"race-{race_id}")

        record = _RaceRecord(race_id=race_id, runner=runner, observer=observer, thread=thread)
        with self._lock:
            self._races[race_id] = record

        thread.start()
        logger.info(f"已启动比赛线程: {race_id}")
        return race_id

    # ------------------------------------------------------------------

    def get_race_status(self, race_id: str) -> Optional[str]:
        """返回比赛状态：waiting / running / completed / error / cancelled / None"""
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
        """终止正在运行的比赛。优雅停止（写 STOP 文件）并等待 metadata.json 写入。"""
        with self._lock:
            rec = self._races.get(race_id)

        if rec is None or rec.status not in ("waiting", "running"):
            return False

        try:
            rec.runner.graceful_stop()
        except Exception as e:
            logger.warning(f"优雅停止 {race_id} 时异常: {e}")

        # Wait for the runner thread so metadata.json is written before we return
        if rec.thread.is_alive():
            rec.thread.join(timeout=20.0)

        with self._lock:
            if rec.status not in ("completed", "error"):
                rec.status = "cancelled"
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
        if rec is None:
            return None
        proc = rec.runner._webots_proc
        if proc and proc.poll() is None:
            return proc.pid
        return None

    def get_stream_url(self, race_id: str, host: str = None) -> str:
        h = host or Config.get("SIMNODE_HOST", "localhost:8001")
        return f"ws://{h}/race/{race_id}/stream"

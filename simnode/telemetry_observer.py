import asyncio
import json
import logging
import os
import time
from copy import deepcopy
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TelemetryObserver:
    """记录一场比赛的全部快照事件，并实时推送给 Backend。"""

    def __init__(
        self,
        race_id: str,
        recordings_dir: str,
        ws_push_callback: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.race_id    = race_id
        self._lock      = Lock()
        self._buffer:   List[Dict[str, Any]] = []
        self._ws_push   = ws_push_callback

        self._telemetry_path = os.path.join(recordings_dir, race_id, "simnode_events.jsonl")
        self._init_telemetry_file()

    # ------------------------------------------------------------------

    def _init_telemetry_file(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._telemetry_path), exist_ok=True)
            open(self._telemetry_path, "w", encoding="utf-8").close()
            logger.info(f"遥测文件已初始化: {self._telemetry_path}")
        except Exception as e:
            logger.error(f"初始化遥测文件失败 ({self.race_id}): {e}")

    # ------------------------------------------------------------------

    def make_snapshot(self, event_type: str, event_data: Any) -> None:
        """接收仿真事件，写入 telemetry.jsonl 并推送 WebSocket。"""
        snapshot = {
            "race_id":    self.race_id,
            "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "event_type": event_type,
            "event_data": event_data,
        }

        with self._lock:
            self._buffer.append(deepcopy(snapshot))
            self._append_to_file(snapshot)

        if self._ws_push is not None:
            try:
                self._ws_push(snapshot)
            except Exception as e:
                logger.warning(f"推流快照失败 ({self.race_id}, {event_type}): {e}")

    # ------------------------------------------------------------------

    def _append_to_file(self, snapshot: dict) -> None:
        try:
            with open(self._telemetry_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"写入遥测文件失败 ({self.race_id}): {e}")

    # ------------------------------------------------------------------

    def pop_snapshots(self) -> List[Dict[str, Any]]:
        """获取并清空当前所有快照（供轮询模式使用）。"""
        with self._lock:
            snapshots = deepcopy(self._buffer)
            self._buffer = []
        return snapshots

    def get_snapshots(self) -> List[Dict[str, Any]]:
        """获取所有快照，不清空。"""
        with self._lock:
            return deepcopy(self._buffer)

    def snapshot_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    def confirm_telemetry_file(self) -> bool:
        """确认 telemetry.jsonl 存在且非空。"""
        if not os.path.exists(self._telemetry_path):
            logger.warning(f"遥测文件不存在: {self._telemetry_path}")
            return False
        size = os.path.getsize(self._telemetry_path)
        logger.info(f"遥测文件已确认: {size} 字节")
        return size > 0

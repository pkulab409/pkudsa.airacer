import base64
import datetime
import json
import logging
import os
import pathlib
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from simnode.telemetry_observer import TelemetryObserver
from simnode.config.config import Config

logger = logging.getLogger(__name__)


class RaceRunner:
    """每场比赛独立一个实例，负责完整的仿真生命周期。"""

    def __init__(
        self,
        race_id:      str,
        session_type: str,
        total_laps:   int,
        cars:         List[Dict[str, Any]],
        observer:     TelemetryObserver,
    ) -> None:
        self.race_id      = race_id
        self.session_type = session_type
        self.total_laps   = total_laps
        self.cars         = cars   # [{"car_slot", "team_id", "team_name", "code_b64"}]
        self._observer    = observer

        self._webots_proc: Optional[subprocess.Popen] = None
        self._tmp_dir:     Optional[tempfile.TemporaryDirectory] = None
        self._aborted      = False

        self._recordings_dir = str(pathlib.Path(Config.get("RECORDINGS_DIR", "./recordings")).resolve())
        self._race_dir = pathlib.Path(self._recordings_dir) / race_id

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run_race(self) -> Dict[str, Any]:
        self._observer.make_snapshot("race_event", {
            "type":    "RaceStart",
            "race_id": self.race_id,
        })

        try:
            car_configs = self._decode_car_codes()
            config_path = self._write_race_config(car_configs)
            self._launch_webots(config_path)
            exit_code = self._wait_for_webots()
            result = self._read_result(exit_code)

        except Exception as e:
            logger.exception(f"比赛 {self.race_id} 执行异常: {e}")
            self._abort(str(e))
            return {
                "race_id":        self.race_id,
                "finish_reason":  "error",
                "error":          str(e),
                "final_rankings": [],
            }
        finally:
            self._cleanup_tmp()

        self._observer.make_snapshot("race_ended", result)
        return result

    # ------------------------------------------------------------------
    # 代码解码
    # ------------------------------------------------------------------

    def _decode_car_codes(self) -> List[Dict[str, Any]]:
        self._tmp_dir = tempfile.TemporaryDirectory(prefix=f"airacer_{self.race_id}_")
        car_configs = []

        for car in self.cars:
            team_id   = car["team_id"]
            team_name = car.get("team_name", team_id)
            car_slot  = car.get("car_slot", team_id)
            code_b64  = car.get("code_b64", "")

            try:
                code_bytes = base64.b64decode(code_b64)
                code_str   = code_bytes.decode("utf-8")
            except Exception as e:
                raise ValueError(f"队伍 {team_id} 代码 Base64 解码失败: {e}")

            code_path = os.path.join(self._tmp_dir.name, f"{team_id}_controller.py")
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code_str)

            car_configs.append({
                "car_slot":  car_slot,
                "team_id":   team_id,
                "team_name": team_name,
                "code_path": code_path,
            })

            logger.debug(f"队伍 {team_id} 代码已写入: {code_path}")

        return car_configs

    # ------------------------------------------------------------------
    # 生成 race_config.json
    # ------------------------------------------------------------------

    def _write_race_config(self, car_configs: List[Dict]) -> str:
        config = {
            "race_id":        self.race_id,
            "session_type":   self.session_type,
            "total_laps":     self.total_laps,
            "recording_path": str(self._race_dir),
            "cars":           car_configs,
            "created_at":     datetime.datetime.now().isoformat(),
        }

        self._race_dir.mkdir(parents=True, exist_ok=True)

        config_path = os.path.join(self._tmp_dir.name, "race_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info(f"比赛配置已写入: {config_path}")
        return config_path

    # ------------------------------------------------------------------
    # 启动 Webots 子进程
    # ------------------------------------------------------------------

    def _launch_webots(self, config_path: str) -> None:
        webots_bin  = Config.get("WEBOTS_BINARY", "/usr/bin/webots")
        world_file  = Config.get("WEBOTS_WORLD",  "./simnode/webots/worlds/airacer.wbt")
        headless    = Config.get("WEBOTS_HEADLESS", True)

        env = os.environ.copy()
        env["RACE_CONFIG_PATH"] = config_path

        # Always use --batch (suppress dialogs); rendering is required for the overhead Camera.
        # On a headless server, ensure a virtual display (e.g. Xvfb) is available.
        args = [webots_bin, "--batch", world_file]

        logger.info(f"启动 Webots: {args}")
        self._webots_proc = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self._observer.make_snapshot("race_event", {
            "type":    "WebotsLaunched",
            "pid":     self._webots_proc.pid,
            "race_id": self.race_id,
        })

    # ------------------------------------------------------------------
    # 等待 Webots 结束
    # ------------------------------------------------------------------

    def _wait_for_webots(self) -> int:
        timeout = Config.get("RACE_TIMEOUT_SECONDS", 600)

        try:
            exit_code = self._webots_proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning(f"比赛 {self.race_id} 超时，强制终止 Webots")
            self._webots_proc.kill()
            self._webots_proc.wait()
            exit_code = -1

        return exit_code

    # ------------------------------------------------------------------
    # 读取结果
    # ------------------------------------------------------------------

    def _read_result(self, webots_exit_code: int) -> Dict[str, Any]:
        metadata_path = self._race_dir / "metadata.json"

        if not metadata_path.exists():
            return {
                "race_id":        self.race_id,
                "finish_reason":  "no_metadata" if webots_exit_code == 0 else "webots_crash",
                "final_rankings": [],
            }

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取结果文件失败 ({self.race_id}): {e}")
            return {
                "race_id":        self.race_id,
                "finish_reason":  "read_error",
                "final_rankings": [],
            }

    # ------------------------------------------------------------------
    # 异常终止
    # ------------------------------------------------------------------

    def _abort(self, reason: str) -> None:
        self._aborted = True
        self._observer.make_snapshot("race_error", {
            "error_type": "runner_abort",
            "message":    reason,
        })
        self.force_stop()

    def graceful_stop(self, timeout: float = 15.0) -> bool:
        """Write STOP signal file and wait for Webots to exit gracefully.
        Returns True if Webots exited cleanly, False if force-killed."""
        stop_file = self._race_dir / "STOP"
        try:
            self._race_dir.mkdir(parents=True, exist_ok=True)
            stop_file.write_text("stop", encoding="utf-8")
            logger.info(f"比赛 {self.race_id}: 已写入 STOP 信号")
        except Exception as e:
            logger.warning(f"写入 STOP 信号失败 ({self.race_id}): {e}")

        if self._webots_proc is None or self._webots_proc.poll() is not None:
            return True

        try:
            self._webots_proc.wait(timeout=timeout)
            logger.info(f"比赛 {self.race_id} Webots 已优雅退出")
            return True
        except subprocess.TimeoutExpired:
            logger.warning(f"比赛 {self.race_id}: 优雅停止超时，强制终止")
            self.force_stop()
            return False
        finally:
            try:
                stop_file.unlink(missing_ok=True)
            except Exception:
                pass

    def force_stop(self) -> None:
        if self._webots_proc and self._webots_proc.poll() is None:
            try:
                self._webots_proc.kill()
                logger.info(f"比赛 {self.race_id} Webots 进程已强制终止")
            except OSError as e:
                logger.warning(f"终止 Webots 进程失败: {e}")

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def _cleanup_tmp(self) -> None:
        if self._tmp_dir is not None:
            try:
                self._tmp_dir.cleanup()
            except Exception:
                pass

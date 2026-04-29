"""
Sim Node 配置模块，对应 Avalon 的 config/config.py 模式。
从 config.yaml 读取，或通过环境变量覆盖。
"""

import os
import pathlib
import yaml

_BASE_DIR = pathlib.Path(__file__).resolve().parent.parent


_DEFAULTS = {
    "SIMNODE_HOST":           "0.0.0.0:8001",
    "RECORDINGS_DIR":         str(_BASE_DIR.parent / "recordings"),
    "WEBOTS_BINARY":          "/usr/bin/webots",
    "WEBOTS_WORLD":           str(_BASE_DIR / "webots" / "worlds" / "airacer.wbt"),
    "RACE_TIMEOUT_SECONDS":   600,
    "LOG_LEVEL":              "INFO",
}

_config: dict = {}


def _load() -> None:
    global _config
    yaml_path = pathlib.Path(__file__).parent / "config.yaml"
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
    else:
        _config = {}


_load()


class Config:
    @staticmethod
    def get(key: str, default=None):
        """读取配置项，优先级：环境变量 > config.yaml > 内置默认值 > default 参数。"""
        if key in os.environ:
            return os.environ[key]
        if key in _config:
            return _config[key]
        if key in _DEFAULTS:
            return _DEFAULTS[key]
        return default

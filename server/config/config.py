"""
Backend 配置模块，对应 Avalon 的 config/config.py 模式。
从 config.yaml 读取，环境变量可覆盖任意键。
"""

import os
import pathlib
import yaml

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # 项目根目录

_DEFAULTS = {
    "DB_PATH":             str(_ROOT / "server" / "database" / "race.db"),
    "RECORDINGS_DIR":      str(_ROOT / "recordings"),
    "SUBMISSIONS_DIR":     str(_ROOT / "submissions"),
    "ADMIN_PASSWORD":      "12345",
    "SERVER_HOST":         "0.0.0.0",
    "SERVER_PORT":         "8000",
    "SIMNODE_URL":         "http://localhost:8001",   # Sim Node HTTP 基地址
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


# ---------------------------------------------------------------------------
# 便捷常量（向后兼容旧的 config.py 导入方式）
# ---------------------------------------------------------------------------
DB_PATH          = Config.get("DB_PATH")
RECORDINGS_DIR   = Config.get("RECORDINGS_DIR")
SUBMISSIONS_DIR  = Config.get("SUBMISSIONS_DIR")
ADMIN_PASSWORD   = Config.get("ADMIN_PASSWORD")
SERVER_HOST      = Config.get("SERVER_HOST")
SERVER_PORT      = int(Config.get("SERVER_PORT"))
SIMNODE_URL      = Config.get("SIMNODE_URL")

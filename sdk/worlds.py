"""sdk/worlds.py — 赛道与车型目录（单一信息源）

列出 ``simnode/webots/worlds/*.wbt`` 中可用的赛道、以及每条赛道里
``DEF car_N <CarProto>`` 指定的车型，供：

* ``sdk/run_local.py``  —— ``--world`` 支持短名、``--list-worlds`` 打印目录
* ``sdk/make_local_config.py`` —— 生成 ``race_config.json`` 时回填 ``car_model``

如果将来新增或改动赛道，**只需同步更新本文件**的 ``WORLDS`` 常量即可，
不需要动 CLI 代码。

与世界文件保持同步的硬约束：每条 ``WorldEntry.cars`` 的顺序和内容必须
与该 ``.wbt`` 里 ``DEF car_N CarXxx`` 的实际 proto 类型一致。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# 常量：仓库根 / 世界目录
# ---------------------------------------------------------------------------

SDK_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SDK_DIR.parent
WORLDS_DIR = REPO_ROOT / "simnode" / "webots" / "worlds"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CarModel:
    """一辆车的元数据（用于在文档/日志里展示，supervisor 不读）。"""
    proto: str            # Webots PROTO 名，如 "CarPhoenix"
    color: str            # 人类可读颜色描述
    nickname: str         # 中文昵称
    description: str = ""

    def label(self) -> str:
        return f"{self.proto} ({self.nickname} / {self.color})"


@dataclass(frozen=True)
class WorldEntry:
    """一个 .wbt 赛道的元数据。"""
    key: str              # 短名，如 "basic"
    wbt: str              # 相对 WORLDS_DIR 的文件名
    title: str            # 人类可读标题
    description: str      # 一句话简介
    cars: dict[str, CarModel]   # car_slot 名 -> CarModel

    @property
    def path(self) -> pathlib.Path:
        return WORLDS_DIR / self.wbt

    @property
    def slots(self) -> list[str]:
        return list(self.cars.keys())


# ---------------------------------------------------------------------------
# 车型目录（与 simnode/webots/protos/CAR_UPGRADE_SUMMARY.md 对齐）
# ---------------------------------------------------------------------------

_PHOENIX = CarModel("CarPhoenix", "烈焰红", "凤凰", "流线型设计，金色赛车条纹")
_THUNDER = CarModel("CarThunder", "电光蓝", "雷霆", "肌肉车风格，白色闪电条纹")
_VIPER   = CarModel("CarViper",   "毒蛇绿", "毒蛇", "亮绿色调，极速风格")
_NOVA    = CarModel("CarNova",    "新星黄", "新星", "橙色赛车条纹，闪电风格")
_FROST   = CarModel("CarFrost",   "冰霜白", "冰霜", "浅蓝色条纹，极光效果")
_SHADOW  = CarModel("CarShadow",  "暗夜黑", "暗影", "深色调，隐形车风格")


# ---------------------------------------------------------------------------
# 赛道目录
# ---------------------------------------------------------------------------

# track_basic / track_complex 采用相同的 6 车布局（仅赛道形状不同）
_STANDARD_6CAR_SLOTS: dict[str, CarModel] = {
    "car_1": _PHOENIX,
    "car_2": _THUNDER,
    "car_3": _VIPER,
    "car_4": _NOVA,
    "car_5": _FROST,
    "car_6": _SHADOW,
}


WORLDS: dict[str, WorldEntry] = {
    "basic": WorldEntry(
        key="basic",
        wbt="track_basic.wbt",
        title="Basic Oval Track（基础椭圆赛道）",
        description="入门赛道：两条直道 + 两段大弧弯。适合首次调参。",
        cars=dict(_STANDARD_6CAR_SLOTS),
    ),
    "complex": WorldEntry(
        key="complex",
        wbt="track_complex.wbt",
        title="Complex Track（复杂赛道）",
        description="进阶赛道：复合弯 + 发卡 + S 弯，考验循线鲁棒性。",
        cars=dict(_STANDARD_6CAR_SLOTS),
    ),
    "airacer": WorldEntry(
        key="airacer",
        wbt="airacer.wbt",
        title="AI Racer Demo（旧版演示赛道）",
        description="最早的 demo 赛道，使用手写 Robot 节点（非 Car 系列 PROTO）。",
        cars={
            "car_1": CarModel("Robot", "红", "demo-1", "手写 Robot 节点"),
            "car_2": CarModel("Robot", "红", "demo-2", "手写 Robot 节点"),
            "car_3": CarModel("Robot", "红", "demo-3", "手写 Robot 节点"),
            "car_4": CarModel("Robot", "红", "demo-4", "手写 Robot 节点"),
        },
    ),
}


DEFAULT_WORLD_KEY = "basic"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def resolve_world(world_arg: Optional[str]) -> WorldEntry:
    """将 ``--world`` 的用户输入解析为 ``WorldEntry``。

    支持三种形式：
      1. 短名（如 ``basic`` / ``complex`` / ``airacer``）
      2. ``.wbt`` 文件名（如 ``track_basic.wbt``）
      3. 绝对/相对路径

    如果是第 3 种且不在目录中，将返回一个 "fallback" ``WorldEntry``
    （cars 为空字典），调用方仍可按路径启动 Webots，但就无法做 slot 校验。
    """
    if not world_arg:
        return WORLDS[DEFAULT_WORLD_KEY]

    # 1. 短名
    if world_arg in WORLDS:
        return WORLDS[world_arg]

    # 2. 文件名精确匹配
    for w in WORLDS.values():
        if w.wbt == world_arg:
            return w

    # 3. 绝对/相对路径
    p = pathlib.Path(world_arg).expanduser()
    if not p.is_absolute():
        # 相对 REPO_ROOT 试一次
        alt = (REPO_ROOT / p).resolve()
        if alt.is_file():
            p = alt
    p = p.resolve() if p.exists() else p
    # 文件名再匹配一次（用户可能给的是仓库里已登记的世界的完整路径）
    for w in WORLDS.values():
        if p == w.path.resolve():
            return w
    # 未登记的路径：返回无 slot 信息的 stub
    return WorldEntry(
        key="(custom)",
        wbt=str(p),
        title=f"自定义世界文件 ({p.name})",
        description="未在 sdk/worlds.py 中登记，无法做 car_slot 校验。",
        cars={},
    )


def format_catalog() -> str:
    """返回一段多行人类可读字符串，列出所有世界与车位。"""
    lines = ["可用赛道（--world 支持短名、文件名或完整路径）："]
    for w in WORLDS.values():
        exist = "✓" if w.path.is_file() else "✗ 缺失"
        lines.append(f"")
        lines.append(f"  [{w.key}]  {w.title}   {exist}")
        lines.append(f"      文件: simnode/webots/worlds/{w.wbt}")
        lines.append(f"      简介: {w.description}")
        lines.append(f"      车位（--car-slot）:")
        for slot, car in w.cars.items():
            lines.append(f"        - {slot:<6}  {car.label()}")
    lines.append("")
    lines.append(f"默认赛道：{DEFAULT_WORLD_KEY}  （即 {WORLDS[DEFAULT_WORLD_KEY].wbt}）")
    return "\n".join(lines)


__all__ = [
    "CarModel",
    "WorldEntry",
    "WORLDS",
    "DEFAULT_WORLD_KEY",
    "REPO_ROOT",
    "WORLDS_DIR",
    "resolve_world",
    "format_catalog",
]

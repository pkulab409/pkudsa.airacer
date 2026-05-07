"""
sdk/tests/test_worlds.py — sdk/worlds.py 的一致性测试

确保 ``sdk/worlds.py`` 里登记的赛道和车位与 ``simnode/webots/worlds/*.wbt``
文件里的 ``DEF car_N CarXxx`` 节点一一对应。任何一方改动都必须同步更新，
否则 ``run_local.py --car-slot`` 的校验会漏报/误报。

覆盖：
  * 每个 WorldEntry 对应的 .wbt 文件存在
  * 每个 slot 在 .wbt 里真的有同名 DEF
  * 对应 DEF 的 PROTO 类型与 CarModel.proto 一致
  * .wbt 里没有"多出来"的 slot（catalog 全覆盖）
  * resolve_world() 对短名/文件名/路径/未登记路径的行为正确
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

SDK_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from worlds import (  # noqa: E402
    DEFAULT_WORLD_KEY,
    WORLDS,
    WorldEntry,
    format_catalog,
    resolve_world,
)


_DEF_CAR_RE = re.compile(r"DEF\s+(car_\d+)\s+(\w+)\s*\{")


def _parse_wbt_cars(wbt: pathlib.Path) -> dict[str, str]:
    """Return {slot_name: proto_type} extracted from the .wbt file."""
    src = wbt.read_text(encoding="utf-8", errors="replace")
    return dict(_DEF_CAR_RE.findall(src))


# ---------------------------------------------------------------------------
# 文件存在与 catalog 一致
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(WORLDS.keys()))
def test_world_file_exists(key):
    w = WORLDS[key]
    assert w.path.is_file(), (
        f"sdk/worlds.py 登记了 {key!r} 指向 {w.path}，但文件不存在。"
    )


@pytest.mark.parametrize("key", list(WORLDS.keys()))
def test_catalog_slots_match_wbt(key):
    w = WORLDS[key]
    actual = _parse_wbt_cars(w.path)

    # 1. 每个登记 slot 都在 .wbt 里
    missing = set(w.cars) - set(actual)
    assert not missing, (
        f"[{key}] catalog 有这些 slot 但 .wbt 里不存在：{sorted(missing)}"
    )

    # 2. PROTO 类型一致
    mismatches = []
    for slot, car in w.cars.items():
        got = actual[slot]
        if car.proto != got:
            mismatches.append(f"{slot}: catalog={car.proto} wbt={got}")
    assert not mismatches, (
        f"[{key}] catalog 与 .wbt 的 PROTO 类型不一致：{mismatches}"
    )

    # 3. .wbt 里没有多余 slot（避免新加了车位却忘记登记）
    extra = set(actual) - set(w.cars)
    assert not extra, (
        f"[{key}] .wbt 里有多出来的 slot 未登记到 sdk/worlds.py: "
        f"{sorted(extra)}"
    )


# ---------------------------------------------------------------------------
# resolve_world 行为
# ---------------------------------------------------------------------------

def test_resolve_world_by_short_name():
    w = resolve_world("basic")
    assert w.key == "basic"
    assert w.wbt.endswith("track_basic.wbt")


def test_resolve_world_by_filename():
    w = resolve_world("track_complex.wbt")
    assert w.key == "complex"


def test_resolve_world_default_when_empty():
    w = resolve_world(None)
    assert w.key == DEFAULT_WORLD_KEY


def test_resolve_world_unknown_path_returns_stub(tmp_path):
    stub_path = tmp_path / "made_up.wbt"
    stub_path.write_text("#VRML_SIM R2025a utf8\n", encoding="utf-8")
    w = resolve_world(str(stub_path))
    # 未登记：cars 为空，但 key 含提示符
    assert isinstance(w, WorldEntry)
    assert w.cars == {}
    assert "custom" in w.key


# ---------------------------------------------------------------------------
# 打印函数不抛异常，并且默认赛道在输出里
# ---------------------------------------------------------------------------

def test_format_catalog_mentions_all_worlds():
    text = format_catalog()
    for key in WORLDS:
        assert f"[{key}]" in text, f"format_catalog 缺少 {key!r}"
    assert DEFAULT_WORLD_KEY in text

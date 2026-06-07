"""
Race bracket (tournament format) auto-computation based on team count.

赛制（25队版本）：
  1. 资格赛 (qualification) — 每队单独跑 1 圈，管理员手动淘汰 1 队
  2. 排位赛 (placement)     — 每批 6 车 × 4 批，综合成绩取前 12 晋级
  3. 分组赛 (group_stage)   — 每批 6 车 × 2 组，每组前 4 晋级 → 8 队
  4. 半决赛 (semi)          — 每批 4 车 × 2 场，每场前 2 晋级 → 4 队
  5. 决赛 (final)           — 4 车同时跑，决出排名
"""

import math

# ── 固定配置（25 队专用） ──────────────────────────────────────────

CARS = {
    "qualification": 1,
    "placement": 6,
    "group_stage": 6,
    "semi": 4,
    "final": 4,
}

LAPS = {
    "qualification": 1,
    "placement": 1,
    "group_stage": 3,
    "semi": 3,
    "final": 5,
}

_TEAM_CAP = 25  # 此赛制支持的队伍数上限


# ── 各阶段晋级数（不含 qualification，管理员手动淘汰） ────────

_ADVANCEMENT: dict[str, int] = {
    "placement": 12,
    "group_stage": 8,
    "semi": 4,
}


# ── 当队伍数较少时的降级赛制 ─────────────────────────────────

_FALLBACK_CARS = {
    "qualification": 1,
    "placement": 4,
    "group_stage": 4,
    "semi": 4,
    "final": 4,
}

_FALLBACK_LAPS = {
    "qualification": 1,
    "placement": 1,
    "group_stage": 3,
    "semi": 3,
    "final": 5,
}


def compute_bracket(team_count: int) -> dict:
    """
    Compute tournament bracket for a zone.

    Returns:
      stages             — 阶段名称列表
      team_count         — 输入队伍数
      cars_per_session   — {阶段: 每场车数}
      laps_per_stage     — {阶段: 圈数}
      advancement        — {阶段: 晋级数}
      sessions_per_stage — {阶段: 场次数}
    """
    if team_count <= 0:
        return {
            "stages": [],
            "team_count": team_count,
            "cars_per_session": {},
            "laps_per_stage": {},
            "advancement": {},
            "sessions_per_stage": {},
        }

    # ── 正式赛制（25 队满配） ────────────────────────────────
    if team_count >= 20:
        stages = ["qualification", "placement", "group_stage", "semi", "final"]
        cars = dict(CARS)
        laps = dict(LAPS)
        adv = dict(_ADVANCEMENT)
        sessions = _compute_sessions_25(team_count)

    # ── 中间赛制（去掉资格赛） ──────────────────────────────
    elif team_count >= 10:
        stages = ["placement", "group_stage", "semi", "final"]
        cars = {k: _FALLBACK_CARS[k] for k in stages}
        laps = {k: _FALLBACK_LAPS[k] for k in stages}
        adv = {}
        sessions = {}
        current = team_count
        for stage in stages:
            sessions[stage] = max(1, math.ceil(current / cars[stage]))
            if stage in _ADVANCEMENT:
                # 按比例缩放晋级数
                ratio = _ADVANCEMENT[stage] / _TEAM_CAP
                adv[stage] = max(1, min(current - 1, round(team_count * ratio)))
            current = adv.get(stage, 2)

    # ── 小队赛制（placement → semi → final） ────────────────
    elif team_count >= 5:
        stages = ["placement", "semi", "final"]
        cars = {"placement": 4, "semi": 4, "final": 4}
        laps = {"placement": 1, "semi": 3, "final": 5}
        sessions = {"placement": max(1, math.ceil(team_count / 4))}
        adv = {"placement": min(team_count, 4)}
        sessions["semi"] = max(1, math.ceil(adv["placement"] / 4))
        adv["semi"] = sessions["semi"] * 2
        sessions["final"] = 1

    # ── 超小队（placement → final） ─────────────────────────
    else:
        stages = ["placement", "final"]
        cars = {"placement": 4, "final": 4}
        laps = {"placement": 1, "final": 5}
        sessions = {"placement": 1, "final": 1}
        adv = {}

    return {
        "stages": stages,
        "team_count": team_count,
        "cars_per_session": cars,
        "laps_per_stage": laps,
        "advancement": adv,
        "sessions_per_stage": sessions,
    }


def _compute_sessions_25(team_count: int) -> dict[str, int]:
    """25 队配置的场次计算。"""
    return {
        "qualification": team_count,  # 每队 1 场
        "placement": max(1, math.ceil(min(team_count, 24) / 6)),  # 24 队 ÷ 6
        "group_stage": 2,  # 固定 2 组
        "semi": 2,  # 固定 2 场
        "final": 1,  # 固定 1 场
    }


# ---------------------------------------------------------------------------
# 25 队完整示例
# ---------------------------------------------------------------------------
#
# >>> compute_bracket(25)
# {
#     "stages": ["qualification", "placement", "group_stage", "semi", "final"],
#     "team_count": 25,
#     "cars_per_session": {
#         "qualification": 1,  "placement": 6,  "group_stage": 6,  "semi": 4,  "final": 4,
#     },
#     "laps_per_stage": {
#         "qualification": 1,  "placement": 1,  "group_stage": 3,  "semi": 3,  "final": 5,
#     },
#     "advancement": {
#         "placement": 12,  "group_stage": 8,  "semi": 4,
#     },
#     "sessions_per_stage": {
#         "qualification": 25,  "placement": 4,  "group_stage": 2,  "semi": 2,  "final": 1,
#     },
# }

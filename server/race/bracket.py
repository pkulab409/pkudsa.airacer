"""
Race bracket (tournament format) auto-computation based on team count.

赛制（25队版本）：
  1. 资格赛 (qualification) — 每队单独跑 1 圈，管理员手动淘汰 1 队
  2. 排位赛 (placement)     — 每批 6 车 × 4 批，综合成绩取前 12 晋级
  3. 分组赛 (group_stage)   — 每批 6 车 × 2 组，每组前 4 晋级 → 8 队
  4. 半决赛 (semi)          — 每批 4 车 × 2 场，每场前 2 晋级 → 4 队
  5. 决赛 (final)           — 4 车同时跑，决出排名

小赛区（13-14 队版本）：
  1. 排位赛 (placement)     — 每批最多 5 车 × 3 批，综合成绩取前 12 晋级
  2. 分组赛 (group_stage)   — 每批 6 车 × 2 组，每组前 4 晋级 → 8 队
  3. 半决赛 (semi)          — 每批 4 车 × 2 场，每场前 2 晋级 → 4 队
  4. 决赛 (final)           — 4 车同时跑，决出排名
"""

import math

# ── 固定配置（25 队专用） ──────────────────────────────────────────

_CARS_25 = {
    "qualification": 1,
    "placement": 6,
    "group_stage": 6,
    "semi": 4,
    "final": 4,
}

_LAPS_25 = {
    "qualification": 1,
    "placement": 1,
    "group_stage": 3,
    "semi": 3,
    "final": 5,
}

_ADVANCEMENT: dict[str, int] = {
    "placement": 12,
    "group_stage": 8,
    "semi": 4,
}

# ── 小赛区配置（11-14 队，按规则文档 v2.8） ────────────────────

_CARS_SMALL = {
    "placement": 5,  # 每批最多 5 辆
    "group_stage": 6,
    "semi": 4,
    "final": 4,
}

_LAPS_SMALL = {
    "placement": 1,
    "group_stage": 3,
    "semi": 3,
    "final": 5,
}

_SESSIONS_SMALL = {
    "placement": 3,  # 3 批
    "group_stage": 2,  # 2 组
    "semi": 2,
    "final": 1,
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

    # ── 25 队满配赛制 ────────────────────────────────────────
    if team_count >= 20:
        stages = ["qualification", "placement", "group_stage", "semi", "final"]
        cars = dict(_CARS_25)
        laps = dict(_LAPS_25)
        adv = dict(_ADVANCEMENT)
        sessions = _compute_sessions_25(team_count)

    # ── 小赛区（13-14 队专用，规则文档 v2.8） ────────────────
    elif team_count >= 11:
        stages = ["placement", "group_stage", "semi", "final"]
        cars = dict(_CARS_SMALL)
        laps = dict(_LAPS_SMALL)
        adv = dict(_ADVANCEMENT)
        sessions = dict(_SESSIONS_SMALL)

    # ── 其他（< 11 队，保持基本结构由助教手动调整） ──────────
    elif team_count >= 5:
        stages = ["placement", "group_stage", "semi", "final"]
        cars = {"placement": 4, "group_stage": 4, "semi": 4, "final": 4}
        laps = {"placement": 1, "group_stage": 3, "semi": 3, "final": 5}
        adv = {}
        sessions = {}
        current = team_count
        for stage in stages:
            sessions[stage] = max(1, math.ceil(current / cars[stage]))
            if stage == "placement":
                adv[stage] = min(team_count, 12)
            elif stage == "group_stage":
                adv[stage] = min(adv.get("placement", team_count), 8)
            elif stage == "semi":
                adv[stage] = min(adv.get("group_stage", 0), 4)
            current = adv.get(stage, 2)

    # ── 极小队（直接决赛） ───────────────────────────────────
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

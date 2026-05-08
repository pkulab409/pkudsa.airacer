"""
Race bracket (tournament format) auto-computation based on team count.

Given N teams in a zone, computes:
- Which stages are needed (placement / group_stage / semi / final)
- How many teams advance from each stage
- Sessions (matches) per stage
- Laps per stage
- Max cars per session per stage

Rules:
    <= 4 teams: placement -> final
    5-8 teams:  placement -> semi -> final
    >= 9 teams: placement -> group_stage -> semi -> final

Placement / group_stage: max 3 cars per session, semi / final: max 4.
Placement laps: 2 (time trial), group_stage: 3, semi: 3, final: 5.

Advancement (>=9 teams):
    placement:    all teams advance (placement is for snake-draft seeding)
    group_stage:  top 1 per session + fastest 2nd place -> semi
    semi:         top 2 per session -> final
"""

import math

LAPS = {"placement": 2, "group_stage": 3, "semi": 3, "final": 5}
CARS = {"placement": 4, "group_stage": 4, "semi": 4, "final": 4}


def compute_bracket(team_count: int) -> dict:
    """
    Compute tournament bracket for a zone with team_count teams.

    Returns a dict with:
      stages:             list of stage names in order
      team_count:         input value
      cars_per_session:   {stage: max cars per session}
      laps_per_stage:     {stage: laps per race}
      advancement:        {stage: how many teams advance to next stage}
      sessions_per_stage: {stage: number of race sessions needed}
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

    if team_count <= 4:
        stages = ["placement", "final"]
    elif team_count <= 8:
        stages = ["placement", "semi", "final"]
    else:
        stages = ["placement", "group_stage", "semi", "final"]

    sessions: dict[str, int] = {}
    adv: dict[str, int] = {}
    current = team_count

    for stage in stages:
        # 当前阶段所需场次 = 队伍数 ÷ 每场最大车数，向上取整，至少1场
        sessions[stage] = max(1, math.ceil(current / CARS[stage]))

        if stage == "placement":  # 排位赛
            if team_count >= 9:
                adv["placement"] = (
                    team_count  # 9队以上：所有队伍都晋级，排位赛仅用于蛇形分组种子排位
                )
            else:
                # 8队以下：取队伍数与4的较小值，即最多4队晋级
                adv["placement"] = min(team_count, 4)
        elif stage == "group_stage":
            # 小组赛：每组第1名直接晋级 + 成绩最好的第2名（共 sessions+1 队）
            adv["group_stage"] = sessions["group_stage"] + 1
        elif stage == "semi":
            # 半决赛：每组前2名晋级决赛
            adv["semi"] = sessions["semi"] * 2
        # final为最终阶段，无晋级

        current = adv.get(stage, 2)

    return {
        "stages": stages,
        "team_count": team_count,
        "cars_per_session": {s: CARS[s] for s in stages},
        "laps_per_stage": {s: LAPS[s] for s in stages},
        "advancement": adv,
        "sessions_per_stage": sessions,
    }


# ---------------------------------------------------------------------------
# 24 队示例
# ---------------------------------------------------------------------------
#
# >>> compute_bracket(24)
# {
#     "stages": ["placement", "group_stage", "semi", "final"],
#     "team_count": 24,
#     "cars_per_session": {
#         "placement": 4,
#         "group_stage": 4,
#         "semi": 4,
#         "final": 4,
#     },
#     "laps_per_stage": {
#         "placement": 2,
#         "group_stage": 3,
#         "semi": 3,
#         "final": 5,
#     },
#     "advancement": {
#         "placement": 24,      # 排位赛：全部晋级，仅用于蛇形分组种子排位
#         "group_stage": 7,     # 小组赛：6组第1 + 最佳第2 → 7队进半决赛
#         "semi": 4,            # 半决赛：2组 × 每组前2 → 4队进决赛
#     },
#     "sessions_per_stage": {
#         "placement": 6,       # ceil(24/4) = 6 场排位赛
#         "group_stage": 6,     # ceil(24/4) = 6 个小组
#         "semi": 2,            # ceil(7/4)  = 2 场半决赛
#         "final": 1,           # ceil(4/4)  = 1 场决赛
#     },
# }

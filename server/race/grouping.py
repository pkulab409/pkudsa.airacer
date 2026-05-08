"""
Snake-draft grouping and advancer selection for tournament stages.
蛇形分组 & 各阶段晋级筛选 —— 纯计算模块，不涉及数据库 I/O。

配合 bracket.py 使用：
  - bracket.py 算出每个阶段需要多少场比赛（session）
  - grouping.py 把具体队伍分配到各场比赛，并决定谁晋级

三个函数的关系：
  snake_draft_group()         排位赛后 → 蛇形分组到小组赛各场
  select_group_stage_advancers()  小组赛后 → 筛选晋级半决赛的队伍
  select_semi_finalists()         半决赛后 → 筛选晋级决赛的队伍
"""


def snake_draft_group(ranked_team_ids: list[str], num_sessions: int) -> list[list[str]]:
    """
    蛇形（ serpentine / snake-draft ）分组。

    常用于排位赛结束后，按排名将队伍均匀分配到 K 个小组，
    使得各小组实力尽可能均衡。

    算法：
        第1轮（正序）:  第1名→组0, 第2名→组1, ..., 第K名→组K-1
        第2轮（逆序）:  第K+1名→组K-1, ..., 第2K名→组0
        第3轮（正序）:  ...
        以此类推，正序-逆序交替。

    ranked_team_ids: 按排位赛成绩排序的队伍 ID 列表，最优在前（索引0 = 第1名）。
    num_sessions:    K = 分组数（即 group_stage 的比赛场数）。

    返回: K 个列表，每个列表包含分配到该场比赛的队伍 ID。

    示例（6队, 3场）:
        组0 ← 第1名, 第6名
        组1 ← 第2名, 第5名
        组2 ← 第3名, 第4名

    示意图:
        轮次0（正序）:  组0: rank1    组1: rank2    组2: rank3
        轮次1（逆序）:  组0: rank6    组1: rank5    组2: rank4
    """
    if num_sessions <= 0:
        raise ValueError("num_sessions must be > 0")

    K = num_sessions
    groups: list[list[str]] = [[] for _ in range(K)]  # 初始化 K 个空组

    for i, tid in enumerate(ranked_team_ids):
        round_num = i // K  # 当前是第几轮（0-based）
        pos_in_round = i % K  # 本轮内的位置（0 ~ K-1）
        if round_num % 2 == 0:
            # 偶数轮（0, 2, 4...）：正序分配
            session = pos_in_round
        else:
            # 奇数轮（1, 3, 5...）：逆序分配
            session = K - 1 - pos_in_round
        groups[session].append(tid)

    return groups


def select_group_stage_advancers(session_results: list[dict]) -> list[str]:
    """
    小组赛 → 半决赛 的晋级筛选。

    规则: 每组第1名全部晋级 + 所有第2名中完赛时间最短的那个也晋级。

    这是 bracket.py 中 "advancement.group_stage = sessions + 1" 的具体实现：
    K 个小组，K 个第1名 + 1 个最佳第2名 = K+1 队晋级。

    session_results: 每场比赛的结果列表，格式:
        [
            {
                "session_id": "...",
                "rankings": [
                    {"team_id": "...", "rank": 1, "finish_time": 123.4, "best_lap_time": 30.2},
                    ...
                ]
            },
            ...
        ]

    返回: 晋级半决赛的队伍 ID 列表。
    """
    winners: list[str] = []  # 各组第一名
    runner_ups: list[tuple[str, float]] = []  # 各组第二名 (team_id, finish_time)

    for sr in session_results:
        # 按名次排序
        rankings = sorted(sr.get("rankings", []), key=lambda r: r.get("rank", 99))
        if not rankings:
            continue

        # 第一名直接晋级
        winners.append(rankings[0]["team_id"])

        # 收集第二名及其完赛时间，用于后续比较
        if len(rankings) >= 2:
            ru = rankings[1]
            ft = ru.get("finish_time") or ru.get("best_lap_time")
            if ft is not None:
                runner_ups.append((ru["team_id"], ft))

    # 所有第二名中完赛时间最短的（即成绩最好的）也晋级
    if runner_ups:
        runner_ups.sort(key=lambda x: x[1])  # 按完赛时间升序，最快的在前
        winners.append(runner_ups[0][0])  # 最快的第二名

    return winners


def select_semi_finalists(session_results: list[dict]) -> list[str]:
    """
    半决赛 → 决赛 的晋级筛选。

    规则: 每场半决赛的前2名晋级决赛。

    这是 bracket.py 中 "advancement.semi = sessions * 2" 的具体实现：
    M 场半决赛，每场取前2名 = 2M 队晋级决赛。

    session_results: 每场半决赛结果，格式同 select_group_stage_advancers。

    返回: 晋级决赛的队伍 ID 列表。
    """
    advancers: list[str] = []
    for sr in session_results:
        rankings = sorted(sr.get("rankings", []), key=lambda r: r.get("rank", 99))
        # 取前2名晋级
        for r in rankings[:2]:
            advancers.append(r["team_id"])
    return advancers

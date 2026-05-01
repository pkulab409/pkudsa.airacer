import pytest
from server.race.bracket import compute_bracket, _compute_advancement

def test_compute_bracket_zero_teams():
    result = compute_bracket(0)
    assert result["stages"] == []
    assert result["team_count"] == 0

def test_compute_bracket_small_teams():
    # 1-4 teams: qualifying -> final
    result = compute_bracket(3)
    assert result["stages"] == ["qualifying", "final"]
    assert result["advancement"]["qualifying"] == 3
    assert result["sessions_per_stage"]["qualifying"] == 1
    assert result["sessions_per_stage"]["final"] == 1

def test_compute_bracket_medium_teams():
    # 5-8 teams: qualifying -> semi -> final
    result = compute_bracket(6)
    assert result["stages"] == ["qualifying", "semi", "final"]
    assert result["advancement"]["qualifying"] == 4
    assert result["advancement"]["semi"] == 2
    assert result["sessions_per_stage"]["qualifying"] == 2
    assert result["sessions_per_stage"]["semi"] == 1
    assert result["sessions_per_stage"]["final"] == 1

def test_compute_bracket_large_teams():
    # >8 teams: qualifying -> group_race -> semi -> final
    result = compute_bracket(12)
    assert result["stages"] == ["qualifying", "group_race", "semi", "final"]
    assert result["advancement"]["qualifying"] == 9  # ceil(12 * 0.75)
    assert result["advancement"]["group_race"] == 4
    assert result["advancement"]["semi"] == 2
    assert result["sessions_per_stage"]["qualifying"] == 3
    assert result["sessions_per_stage"]["group_race"] == 3  # ceil(9/4)
    assert result["sessions_per_stage"]["semi"] == 1
    assert result["sessions_per_stage"]["final"] == 1

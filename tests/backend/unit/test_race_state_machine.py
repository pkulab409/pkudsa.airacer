import pytest
from server.race.state_machine import StateMachine, RaceState, get_zone_sm, all_running_zones, remove_zone_sm

def test_state_machine_initial_state():
    sm = StateMachine()
    assert sm.state == RaceState.IDLE
    assert sm.is_running() is False

def test_state_machine_transition_valid():
    sm = StateMachine()
    sm.transition(RaceState.QUALIFYING_RUNNING)
    assert sm.state == RaceState.QUALIFYING_RUNNING
    assert sm.is_running() is True
    
    sm.transition(RaceState.QUALIFYING_FINISHED)
    assert sm.state == RaceState.QUALIFYING_FINISHED
    assert sm.is_running() is False

def test_state_machine_transition_invalid():
    sm = StateMachine()
    with pytest.raises(ValueError) as exc_info:
        sm.transition(RaceState.QUALIFYING_FINISHED)
    assert "Illegal transition" in str(exc_info.value)

@pytest.mark.parametrize("start_state, invalid_target", [
    (RaceState.IDLE, RaceState.QUALIFYING_DONE),
    (RaceState.QUALIFYING_RUNNING, RaceState.GROUP_RACE_RUNNING),
    (RaceState.QUALIFYING_DONE, RaceState.CLOSED),
    (RaceState.GROUP_DONE, RaceState.FINAL_RUNNING),
    (RaceState.SEMI_DONE, RaceState.GROUP_RACE_RUNNING),
    (RaceState.CLOSED, RaceState.FINAL_RUNNING),
])
def test_invalid_transitions(start_state, invalid_target):
    sm = StateMachine()
    sm._state = start_state

    with pytest.raises(ValueError) as exc_info:
        sm.transition(invalid_target)

    assert "Illegal transition" in str(exc_info.value)
    assert sm.state == start_state

def test_state_machine_reset():
    sm = StateMachine()
    sm.transition(RaceState.QUALIFYING_RUNNING)
    sm.reset()
    assert sm.state == RaceState.IDLE

def test_get_zone_sm():
    sm1 = get_zone_sm("zone1")
    sm2 = get_zone_sm("zone1")
    sm3 = get_zone_sm("zone2")
    
    assert sm1 is sm2
    assert sm1 is not sm3

def test_all_running_zones():
    sm1 = get_zone_sm("zone_run_1")
    sm1.transition(RaceState.GROUP_RACE_RUNNING)
    
    sm2 = get_zone_sm("zone_idle_1")
    sm2.reset()
    
    running = all_running_zones()
    assert len(running) >= 1
    assert any(z_id == "zone_run_1" for z_id, _ in running)
    assert not any(z_id == "zone_idle_1" for z_id, _ in running)

def test_remove_zone_sm():
    sm = get_zone_sm("zone_to_remove")
    remove_zone_sm("zone_to_remove")
    
    # Getting it again should create a new instance
    sm_new = get_zone_sm("zone_to_remove")
    assert sm is not sm_new

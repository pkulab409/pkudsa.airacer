import pytest
import json
import os
from server.race.scoring import extract_session_results, extract_test_results

def test_extract_session_results(tmp_path):
    session_id = "test_session_1"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    
    meta_data = {
        "final_rankings": [{"team_id": "t1", "rank": 1}],
        "duration_sim": 120.5,
        "finish_reason": "race_end",
        "teams": ["t1"]
    }
    
    with open(session_dir / "metadata.json", "w") as f:
        json.dump(meta_data, f)
        
    results = extract_session_results(session_id, str(tmp_path))
    
    assert results["duration_sim"] == 120.5
    assert results["finish_reason"] == "race_end"
    assert len(results["final_rankings"]) == 1
    assert results["final_rankings"][0]["team_id"] == "t1"

def test_extract_test_results(tmp_path):
    session_id = "test_session_2"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    
    meta_data = {
        "finish_reason": "race_end",
        "final_rankings": [{
            "team_id": "t1",
            "laps_completed": 3,
            "best_lap_time": 15.2
        }]
    }
    
    with open(session_dir / "metadata.json", "w") as f:
        json.dump(meta_data, f)
        
    telemetry_data = [
        {"events": [{"type": "collision", "severity": "minor"}]},
        {"events": [{"type": "collision", "severity": "major"}]},
        {"events": [{"type": "timeout_warn"}]},
        {"events": [{"type": "collision", "severity": "minor"}]}
    ]
    
    with open(session_dir / "telemetry.jsonl", "w") as f:
        for item in telemetry_data:
            f.write(json.dumps(item) + "\n")
            
    results = extract_test_results(session_id, str(tmp_path))
    
    assert results["laps_completed"] == 3
    assert results["best_lap_time"] == 15.2
    assert results["collisions_minor"] == 2
    assert results["collisions_major"] == 1
    assert results["timeout_warnings"] == 1
    assert results["finish_reason"] == "race_end"

def test_extract_test_results_no_telemetry(tmp_path):
    session_id = "test_session_3"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    
    meta_data = {
        "finish_reason": "timeout",
        "final_rankings": [{
            "team_id": "t1",
            "laps_completed": 1,
            "lap_times": [20.5, None]
        }]
    }
    
    with open(session_dir / "metadata.json", "w") as f:
        json.dump(meta_data, f)
        
    results = extract_test_results(session_id, str(tmp_path))
    
    assert results["laps_completed"] == 1
    assert results["best_lap_time"] == 20.5
    assert results["collisions_minor"] == 0
    assert results["collisions_major"] == 0
    assert results["timeout_warnings"] == 0
    assert results["finish_reason"] == "timeout"

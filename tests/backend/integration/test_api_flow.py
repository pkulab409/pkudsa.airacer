import pytest
import base64
import json
import os
from unittest.mock import patch, MagicMock

def test_full_competition_flow(client, admin_auth, db_conn):
    # 1. Create a zone
    response = client.post("/api/admin/zones", json={
        "id": "integration_zone",
        "name": "Integration Zone",
        "description": "Test Zone",
        "total_laps": 3
    }, headers=admin_auth)
    assert response.status_code == 200
    
    # 2. Register teams
    for i in range(1, 5):
        response = client.post("/api/register", json={
            "zone_id": "integration_zone",
            "team_id": f"team_{i}",
            "team_name": f"Team {i}",
            "password": "password123"
        })
        assert response.status_code == 200
        
    # 3. Submit code for teams
    valid_code = """
def control(img_front, img_rear, speed):
    return 0.5, 0.5
"""
    code_b64 = base64.b64encode(valid_code.encode()).decode()
    
    for i in range(1, 5):
        response = client.post("/api/submit", json={
            "team_id": f"team_{i}",
            "password": "password123",
            "code": code_b64,
            "slot_name": "main"
        })
        assert response.status_code == 200
        
    # 4. Admin sets up a session
    response = client.post("/api/admin/zones/integration_zone/set-session", json={
        "session_type": "qualifying",
        "session_id": "qual_1",
        "team_ids": ["team_1", "team_2", "team_3", "team_4"],
        "total_laps": 3
    }, headers=admin_auth)
    assert response.status_code == 200
    
    # 5. Mock simnode and start race
    with patch("server.blueprints.admin.simnode_start_race") as mock_start:
        mock_start.return_value = {"stream_ws_url": "ws://mock/stream"}
        
        response = client.post("/api/admin/zones/integration_zone/start-race", headers=admin_auth)
        assert response.status_code == 200
        assert response.json()["status"] == "running"
        
        # Verify state machine
        from server.race.state_machine import get_zone_sm
        sm = get_zone_sm("integration_zone")
        assert sm.state.value == "QUALIFYING_RUNNING"
        
    # 6. Mock simnode completion and handle it
    with patch("server.blueprints.admin.simnode_get_status") as mock_status, \
         patch("server.blueprints.admin.simnode_get_result") as mock_result:
        
        mock_status.return_value = "completed"
        mock_result.return_value = {
            "final_rankings": [
                {"team_id": "team_1", "rank": 1, "laps_completed": 3},
                {"team_id": "team_2", "rank": 2, "laps_completed": 3},
                {"team_id": "team_3", "rank": 3, "laps_completed": 3},
                {"team_id": "team_4", "rank": 4, "laps_completed": 3}
            ],
            "duration_sim": 120.0,
            "finish_reason": "race_end",
            "teams": ["team_1", "team_2", "team_3", "team_4"]
        }
        
        # Manually trigger the handler since the background task is hard to test
        import asyncio
        from server.blueprints.admin import _handle_finished
        asyncio.run(_handle_finished("qual_1", "qualifying", "integration_zone"))
        
        assert sm.state.value == "QUALIFYING_FINISHED"
        
    # 7. Finalize qualifying
    response = client.post("/api/admin/zones/integration_zone/finalize", headers=admin_auth)
    assert response.status_code == 200
    assert sm.state.value == "QUALIFYING_DONE"
    
    # 8. Check recordings
    response = client.get("/api/recordings")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(r["session_id"] == "qual_1" for r in data)

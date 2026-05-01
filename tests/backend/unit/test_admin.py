import pytest
from server.blueprints.admin import _get_running_session_id
from concurrent.futures import ThreadPoolExecutor

def test_admin_auth_required(client):
    response = client.get("/api/admin/zones")
    assert response.status_code == 401

def test_admin_auth_success(client, admin_auth):
    response = client.get("/api/admin/zones", headers=admin_auth)
    assert response.status_code == 200

def test_create_zone(client, admin_auth, db_conn):
    response = client.post("/api/admin/zones", json={
        "id": "test_zone_1",
        "name": "Test Zone 1",
        "description": "A test zone",
        "total_laps": 5
    }, headers=admin_auth)
    
    assert response.status_code == 200
    assert response.json()["status"] == "created"
    
    row = db_conn.execute("SELECT * FROM zones WHERE id='test_zone_1'").fetchone()
    assert row is not None
    assert row["name"] == "Test Zone 1"
    assert row["total_laps"] == 5

def test_delete_zone(client, admin_auth, db_conn):
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('test_zone_2', 'Test Zone 2')")
    db_conn.commit()
    
    response = client.delete("/api/admin/zones/test_zone_2", headers=admin_auth)
    assert response.status_code == 200
    
    row = db_conn.execute("SELECT * FROM zones WHERE id='test_zone_2'").fetchone()
    assert row is None

def test_set_session(client, admin_auth, db_conn):
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('test_zone_3', 'Test Zone 3')")
    db_conn.execute("INSERT INTO teams (id, name, password_hash, zone_id) VALUES ('team1', 'Team 1', 'hash', 'test_zone_3')")
    db_conn.execute("INSERT INTO teams (id, name, password_hash, zone_id) VALUES ('team2', 'Team 2', 'hash', 'test_zone_3')")
    db_conn.commit()
    
    response = client.post("/api/admin/zones/test_zone_3/set-session", json={
        "session_type": "group_race",
        "session_id": "group_A",
        "team_ids": ["team1", "team2"],
        "total_laps": 10
    }, headers=admin_auth)
    
    assert response.status_code == 200
    
    from server.race.state_machine import get_zone_sm
    sm = get_zone_sm("test_zone_3")
    assert sm.state.value == "IDLE"

def test_concurrent_set_session(client, admin_auth, db_conn):
    from server.blueprints import admin as admin_module

    db_conn.execute("INSERT INTO zones (id, name) VALUES ('concurrent_zone', 'Concurrent Zone')")
    for idx in range(1, 5):
        db_conn.execute(
            "INSERT INTO teams (id, name, password_hash, zone_id) VALUES (?, ?, 'hash', 'concurrent_zone')",
            (f"concurrent_team_{idx}", f"Concurrent Team {idx}"),
        )
    db_conn.commit()

    def set_session(idx):
        return client.post(
            "/api/admin/zones/concurrent_zone/set-session",
            json={
                "session_type": "group_race",
                "session_id": f"concurrent_session_{idx}",
                "team_ids": [f"concurrent_team_{idx}"],
                "total_laps": idx + 2,
            },
            headers=admin_auth,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(set_session, range(1, 5)))

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert {response.json()["session_id"] for response in responses} == {
        "concurrent_session_1",
        "concurrent_session_2",
        "concurrent_session_3",
        "concurrent_session_4",
    }
    assert all(
        len(admin_module._pending_cars[f"concurrent_session_{idx}"]) == 1
        for idx in range(1, 5)
    )

    rows = db_conn.execute(
        "SELECT id, phase FROM race_sessions WHERE zone_id='concurrent_zone'"
    ).fetchall()
    assert {row["id"] for row in rows} == {
        "concurrent_session_1",
        "concurrent_session_2",
        "concurrent_session_3",
        "concurrent_session_4",
    }
    assert {row["phase"] for row in rows} == {"waiting"}

def test_lock_submissions(client, admin_auth):
    from server.blueprints import submission
    submission.submissions_locked = False
    
    response = client.post("/api/admin/lock-submissions", headers=admin_auth)
    assert response.status_code == 200
    assert submission.submissions_locked is True
    
    # Reset for other tests
    submission.submissions_locked = False

import base64
import pytest
from server.blueprints.submission import _hash_password, _verify_password, _validate_code

def test_password_hashing():
    pwd = "my_secret_password"
    hashed = _hash_password(pwd)
    assert hashed != pwd
    assert _verify_password(pwd, hashed) is True
    assert _verify_password("wrong_password", hashed) is False

def test_invalid_password_hash_returns_false():
    assert _verify_password("password", "not-a-bcrypt-hash") is False

def test_validate_code_valid():
    valid_code = """
def control(img_front, img_rear, speed):
    return 0.5, 0.5
"""
    # Should not raise an exception
    _validate_code(valid_code)

def test_validate_code_syntax_error():
    invalid_code = """
def control(img_front, img_rear, speed)
    return 0.5, 0.5
"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _validate_code(invalid_code)
    assert exc_info.value.status_code == 400
    assert "Syntax error" in exc_info.value.detail

@pytest.mark.parametrize("code, expected_detail", [
    ("import os\n\ndef control(img_front, img_rear, speed):\n    return 0.5, 0.5\n", "Forbidden import: os"),
    ("from subprocess import run\n\ndef control(img_front, img_rear, speed):\n    return 0.5, 0.5\n", "Forbidden import: subprocess"),
    ("def control(img_front, img_rear, speed):\n    __import__('sys')\n    return 0.5, 0.5\n", "Forbidden call: __import__"),
    ("def control(img_front, img_rear, speed):\n    open('/tmp/x')\n    return 0.5, 0.5\n", "Forbidden call: open"),
])
def test_validate_code_forbidden_imports(code, expected_detail):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _validate_code(code)

    assert exc_info.value.status_code == 400
    assert expected_detail in exc_info.value.detail

def test_validate_code_missing_control():
    invalid_code = """
def not_control(img_front, img_rear, speed):
    return 0.5, 0.5
"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _validate_code(invalid_code)
    assert exc_info.value.status_code == 400
    assert "must define a callable named 'control'" in exc_info.value.detail

def test_validate_code_wrong_return_type():
    invalid_code = """
def control(img_front, img_rear, speed):
    return "left", "right"
"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _validate_code(invalid_code)
    assert exc_info.value.status_code == 400
    assert "must return a tuple of 2 floats" in exc_info.value.detail

def test_validate_code_exception_in_control():
    invalid_code = """
def control(img_front, img_rear, speed):
    raise ValueError("Test error")
"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _validate_code(invalid_code)
    assert exc_info.value.status_code == 400
    assert "control() raised an exception" in exc_info.value.detail

def test_submit_code_api(client, db_conn):
    # Setup team
    team_id = "test_team_1"
    pwd = "test_password"
    hashed = _hash_password(pwd)
    db_conn.execute("INSERT INTO zones (id, name) VALUES ('zone1', 'Zone 1')")
    db_conn.execute("INSERT INTO teams (id, name, password_hash, zone_id) VALUES (?, ?, ?, 'zone1')", (team_id, "Test Team", hashed))
    db_conn.commit()
    
    valid_code = """
def control(img_front, img_rear, speed):
    return 0.5, 0.5
"""
    code_b64 = base64.b64encode(valid_code.encode()).decode()
    
    response = client.post("/api/submit", json={
        "team_id": team_id,
        "password": pwd,
        "code": code_b64,
        "slot_name": "main"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["slot_name"] == "main"
    assert "version" in data
    assert "queue_position" in data

def test_submit_code_invalid_password(client, db_conn):
    team_id = "test_team_2"
    pwd = "test_password"
    hashed = _hash_password(pwd)
    db_conn.execute("INSERT INTO teams (id, name, password_hash) VALUES (?, ?, ?)", (team_id, "Test Team 2", hashed))
    db_conn.commit()
    
    response = client.post("/api/submit", json={
        "team_id": team_id,
        "password": "wrong_password",
        "code": "YmFzZTY0",
        "slot_name": "main"
    })
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid password"

def test_activate_slot_api(client, db_conn):
    team_id = "test_team_3"
    pwd = "test_password"
    hashed = _hash_password(pwd)
    db_conn.execute("INSERT INTO teams (id, name, password_hash) VALUES (?, ?, ?)", (team_id, "Test Team 3", hashed))
    
    # Insert dummy submissions
    db_conn.execute("INSERT INTO submissions (id, team_id, code_path, submitted_at, is_active, slot_name, is_race_active) VALUES ('sub1', ?, 'path1', '20230101', 1, 'main', 1)", (team_id,))
    db_conn.execute("INSERT INTO submissions (id, team_id, code_path, submitted_at, is_active, slot_name, is_race_active) VALUES ('sub2', ?, 'path2', '20230102', 1, 'dev', 0)", (team_id,))
    db_conn.commit()
    
    response = client.post("/api/activate", json={
        "team_id": team_id,
        "password": pwd,
        "slot_name": "dev"
    })
    
    assert response.status_code == 200
    assert response.json()["status"] == "activated"
    assert response.json()["slot_name"] == "dev"
    
    # Verify in DB
    row = db_conn.execute("SELECT is_race_active FROM submissions WHERE id='sub2'").fetchone()
    assert row["is_race_active"] == 1
    row = db_conn.execute("SELECT is_race_active FROM submissions WHERE id='sub1'").fetchone()
    assert row["is_race_active"] == 0

def test_get_test_status_api(client, db_conn):
    team_id = "test_team_4"
    pwd = "test_password"
    hashed = _hash_password(pwd)
    db_conn.execute("INSERT INTO teams (id, name, password_hash) VALUES (?, ?, ?)", (team_id, "Test Team 4", hashed))
    
    # Insert dummy submission and test run
    db_conn.execute("INSERT INTO submissions (id, team_id, code_path, submitted_at, is_active, slot_name, is_race_active) VALUES ('sub3', ?, 'path3', '20230103', 1, 'main', 1)", (team_id,))
    db_conn.execute("INSERT INTO test_runs (submission_id, status, queued_at, laps_completed, best_lap_time, collisions_minor, collisions_major, timeout_warnings, finish_reason, finished_at) VALUES ('sub3', 'done', '20230103', 3, 12.5, 0, 0, 0, 'race_end', '20230103')")
    db_conn.commit()
    
    import base64
    auth_str = base64.b64encode(f"{team_id}:{pwd}".encode()).decode()
    
    response = client.get(f"/api/test-status/{team_id}", headers={"Authorization": f"Basic {auth_str}"})
    
    assert response.status_code == 200
    data = response.json()
    assert data["team_id"] == team_id
    assert "main" in data["slots"]
    assert data["slots"]["main"]["is_race_active"] is True
    assert data["slots"]["main"]["queue_status"] == "done"
    assert data["slots"]["main"]["test"]["laps_completed"] == 3

import pytest
import os
import json

def test_get_recordings_empty(client):
    response = client.get("/api/recordings")
    assert response.status_code == 200
    assert response.json() == []

def test_get_recordings_with_data(client, db_conn):
    # The endpoint reads from RECORDINGS_DIR, not the DB
    recordings_dir = os.environ["RECORDINGS_DIR"]
    session_dir = os.path.join(recordings_dir, "session1")
    os.makedirs(session_dir, exist_ok=True)
    
    meta_data = {
        "session_type": "test",
        "zone_id": "zone1",
        "recorded_at": "2023-01-01T12:00:00",
        "finish_reason": "completed",
        "teams": ["team1"],
        "final_rankings": []
    }
    
    with open(os.path.join(session_dir, "metadata.json"), "w") as f:
        json.dump(meta_data, f)
    
    response = client.get("/api/recordings")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "session1"
    assert data[0]["session_type"] == "test"
    assert data[0]["zone_id"] == "zone1"

def test_get_recording_metadata_not_found(client):
    response = client.get("/api/recordings/nonexistent/metadata")
    assert response.status_code == 404

def test_get_recording_metadata_success(client, db_conn):
    recordings_dir = os.environ["RECORDINGS_DIR"]
    session_dir = os.path.join(recordings_dir, "session2")
    os.makedirs(session_dir, exist_ok=True)
    
    meta_data = {
        "session_id": "session2",
        "session_type": "test",
        "zone_id": "zone2"
    }
    
    with open(os.path.join(session_dir, "metadata.json"), "w") as f:
        json.dump(meta_data, f)
    
    response = client.get("/api/recordings/session2/metadata")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "session2"
    assert data["session_type"] == "test"
    assert data["zone_id"] == "zone2"

def test_get_recording_telemetry_not_found(client):
    response = client.get("/api/recordings/nonexistent/telemetry")
    assert response.status_code == 404

def test_corrupted_telemetry_file(client):
    recordings_dir = os.environ["RECORDINGS_DIR"]
    session_dir = os.path.join(recordings_dir, "corrupted_session")
    os.makedirs(session_dir, exist_ok=True)

    with open(os.path.join(session_dir, "metadata.json"), "w") as f:
        json.dump({
            "session_id": "corrupted_session",
            "session_type": "test",
            "zone_id": "zone1",
            "recorded_at": "2023-01-01T12:00:00",
        }, f)

    telemetry_lines = [
        '{"t": 0.0, "cars": []}\n',
        '{"t": 0.1, "cars": [}\n',
        '{"t": 0.2, "cars": []}\n',
    ]
    with open(os.path.join(session_dir, "telemetry.jsonl"), "w") as f:
        f.writelines(telemetry_lines)

    response = client.get("/api/recordings/corrupted_session/telemetry")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.text == "".join(telemetry_lines)

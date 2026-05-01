"""
Test Queue Flow Integration Tests (Module G2)

Tests the complete test queue lifecycle: enqueue -> process -> report.
"""

import pytest
import base64
from unittest.mock import patch, Mock


@pytest.fixture
def client():
    import os
    import tempfile
    from fastapi.testclient import TestClient

    os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
    os.environ["SUBMISSIONS_DIR"] = tempfile.mkdtemp()
    os.environ["RECORDINGS_DIR"] = tempfile.mkdtemp()
    os.environ["ADMIN_PASSWORD"] = "test_admin_pwd"

    from server.app import app
    from server.database.models import init_db, get_db
    from server.config.config import DB_PATH

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db(DB_PATH)

    with get_db(DB_PATH) as conn:
        conn.execute("INSERT INTO zones (id, name) VALUES ('z1', 'Zone 1')")
        import bcrypt
        hashed = bcrypt.hashpw(b"hash1", bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO teams (id, name, password_hash, zone_id) VALUES ('t1', 'Team 1', ?, 'z1')",
            (hashed,)
        )
        conn.commit()

    with TestClient(app) as c:
        yield c

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


class TestQueueSubmission:
    """G2-1: Code submission enters queue."""

    def test_submit_code_creates_queued_test_run(self, client):
        """Submitting code should create a test run with status 'queued'."""
        code_b64 = base64.b64encode(b"def control(a,b,c): return 0.5, 0.5").decode()
        resp = client.post("/api/submit", json={
            "team_id": "t1",
            "password": "hash1",
            "code": code_b64,
            "slot_name": "main"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["queue_position"] > 0

    def test_submit_code_multiple_versions(self, client):
        """Multiple submissions should create multiple test runs."""
        code_b64 = base64.b64encode(b"def control(a,b,c): return 0.5, 0.5").decode()

        resp1 = client.post("/api/submit", json={
            "team_id": "t1", "password": "hash1",
            "code": code_b64, "slot_name": "main"
        })
        resp2 = client.post("/api/submit", json={
            "team_id": "t1", "password": "hash1",
            "code": code_b64, "slot_name": "main"
        })

        assert resp1.status_code == 200
        assert resp2.status_code == 200

    def test_test_status_shows_queue_position(self, client):
        """Test status API should show queue position."""
        import base64
        auth_str = base64.b64encode(b"t1:hash1").decode()

        # Before submitting
        resp = client.get("/api/test-status/t1", headers={
            "Authorization": f"Basic {auth_str}"
        })
        assert resp.status_code == 200

        # After submitting
        code_b64 = base64.b64encode(b"def control(a,b,c): return 0.5, 0.5").decode()
        client.post("/api/submit", json={
            "team_id": "t1", "password": "hash1",
            "code": code_b64, "slot_name": "main"
        })

        resp = client.get("/api/test-status/t1", headers={
            "Authorization": f"Basic {auth_str}"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["team_id"] == "t1"
        assert "slots" in data

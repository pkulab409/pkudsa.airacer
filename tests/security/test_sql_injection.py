"""
SQL Injection Tests (Module K1)

Tests that API endpoints are protected against SQL injection attacks.
"""

import pytest
from fastapi.testclient import TestClient
import os
import tempfile


@pytest.fixture
def client():
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
        conn.execute("INSERT INTO zones (id, name) VALUES ('zone1', 'Zone 1')")
        conn.execute("INSERT INTO teams (id, name, password_hash, zone_id) VALUES ('t1', 'Team 1', 'hash', 'zone1')")
        conn.commit()

    with TestClient(app) as c:
        yield c

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


@pytest.fixture
def admin_auth():
    import base64
    auth_str = base64.b64encode(b"admin:test_admin_pwd").decode()
    return {"Authorization": f"Basic {auth_str}"}


class TestSQLInjectionInTeamID:
    """K1-1: SQL injection through team_id parameter."""

    def test_team_id_sql_injection_register(self, client):
        """Register with SQL injection in team_id should be rejected or safe."""
        malicious_id = "t1' OR '1'='1"
        resp = client.post("/api/register", json={
            "zone_id": "zone1",
            "team_id": malicious_id,
            "team_name": "Test",
            "password": "pwd"
        })
        # Should either succeed with the literal ID or fail validation
        assert resp.status_code in [200, 400, 422]

    def test_team_id_sql_injection_submit(self, client):
        """Submit with SQL injection in team_id."""
        malicious_id = "t1' OR '1'='1"
        import base64
        code_b64 = base64.b64encode(b"def control(a,b,c): return 0.5, 0.5").decode()
        resp = client.post("/api/submit", json={
            "team_id": malicious_id,
            "password": "pwd",
            "code": code_b64,
            "slot_name": "main"
        })
        # Should fail auth, not expose data
        assert resp.status_code == 401

    def test_team_id_sql_injection_test_status(self, client):
        """Test status with SQL injection in team_id."""
        malicious_id = "t1' UNION SELECT * FROM teams--"
        import base64
        auth_str = base64.b64encode(f"{malicious_id}:pwd".encode()).decode()
        resp = client.get(f"/api/test-status/{malicious_id}", headers={
            "Authorization": f"Basic {auth_str}"
        })
        # Should fail auth
        assert resp.status_code in [401, 404]


class TestSQLInjectionInZoneID:
    """K1-2: SQL injection through zone_id parameter."""

    def test_zone_id_sql_injection_create_zone(self, client, admin_auth):
        """Create zone with SQL injection in ID."""
        malicious_id = "zone' UNION SELECT * FROM teams--"
        resp = client.post("/api/admin/zones", json={
            "id": malicious_id,
            "name": "Test Zone",
            "total_laps": 3
        }, headers=admin_auth)
        # Should succeed with literal ID or fail validation
        assert resp.status_code in [200, 400, 422]

    def test_zone_id_sql_injection_get_zone(self, client):
        """Get zone with SQL injection."""
        malicious_id = "zone1' OR '1'='1"
        resp = client.get(f"/api/zones/{malicious_id}")
        # Should return 404 or handle safely
        assert resp.status_code in [200, 404]


class TestSQLInjectionInSessionID:
    """K1-3: SQL injection through session/race_id parameter."""

    def test_session_id_sql_injection_recordings(self, client):
        """Access recordings with SQL injection."""
        malicious_id = "race' UNION SELECT * FROM teams--"
        resp = client.get(f"/api/recordings/{malicious_id}/metadata")
        # Should return 404 or empty, not expose data
        assert resp.status_code in [200, 404, 500]


class TestSQLInjectionInParameters:
    """K1-4: SQL injection through query parameters."""

    def test_sql_injection_team_name(self, client):
        """Team name with SQL injection."""
        malicious_name = "Team'; DROP TABLE teams;--"
        resp = client.post("/api/register", json={
            "zone_id": "zone1",
            "team_id": "safe_id",
            "team_name": malicious_name,
            "password": "pwd"
        })
        # Should succeed with literal name or be sanitized
        assert resp.status_code in [200, 400]

    def test_sql_injection_zone_name(self, client, admin_auth):
        """Zone name with SQL injection."""
        malicious_name = "Zone'; DROP TABLE zones;--"
        resp = client.post("/api/admin/zones", json={
            "id": "safe_zone",
            "name": malicious_name,
            "total_laps": 3
        }, headers=admin_auth)
        # Should succeed with literal name
        assert resp.status_code in [200, 400]


class TestNoDataExposed:
    """K1-5: Verify SQL injection does not expose unauthorized data."""

    def test_no_data_leak_via_error_messages(self, client):
        """Error messages should not reveal database structure."""
        resp = client.get("/api/test-status/nonexistent' OR '1'='1")
        # Error message should be generic
        if resp.status_code != 200:
            data = resp.json()
            assert "detail" in data
            # Should not contain SQL keywords or table names
            detail = data.get("detail", "")
            assert "SELECT" not in detail.upper()
            assert "FROM" not in detail.upper()
            assert "TABLE" not in detail.upper()

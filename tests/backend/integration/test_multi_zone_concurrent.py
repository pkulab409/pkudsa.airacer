"""
Multi-Zone Concurrency Integration Tests (Module G1)

Tests that multiple zones can run simultaneously without interference.
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
        conn.execute("INSERT INTO zones (id, name) VALUES ('z2', 'Zone 2')")
        for i in range(1, 5):
            conn.execute(
                "INSERT INTO teams (id, name, password_hash, zone_id) VALUES (?, ?, ?, 'z1')",
                (f"t{i}", f"Team {i}", f"hash{i}")
            )
        for i in range(5, 9):
            conn.execute(
                "INSERT INTO teams (id, name, password_hash, zone_id) VALUES (?, ?, ?, 'z2')",
                (f"t{i}", f"Team {i}", f"hash{i}")
            )
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


class TestTwoZonesConcurrentSetup:
    """G1-1: Two zones can be set up simultaneously."""

    def test_two_zones_set_session(self, client, admin_auth):
        """Set up sessions for two zones independently."""
        resp1 = client.post("/api/admin/zones/z1/set-session", json={
            "session_type": "qualifying",
            "session_id": "z1_qual",
            "team_ids": ["t1", "t2", "t3", "t4"],
            "total_laps": 3
        }, headers=admin_auth)
        assert resp1.status_code == 200

        resp2 = client.post("/api/admin/zones/z2/set-session", json={
            "session_type": "qualifying",
            "session_id": "z2_qual",
            "team_ids": ["t5", "t6", "t7", "t8"],
            "total_laps": 3
        }, headers=admin_auth)
        assert resp2.status_code == 200


class TestZoneStateIsolation:
    """G1-2: Zone state machines are isolated."""

    def test_zone_states_independent(self, client, admin_auth):
        """State of one zone does not affect another."""
        # Setup both zones
        client.post("/api/admin/zones/z1/set-session", json={
            "session_type": "qualifying",
            "session_id": "z1_qual",
            "team_ids": ["t1", "t2"],
            "total_laps": 3
        }, headers=admin_auth)

        client.post("/api/admin/zones/z2/set-session", json={
            "session_type": "qualifying",
            "session_id": "z2_qual",
            "team_ids": ["t5", "t6"],
            "total_laps": 3
        }, headers=admin_auth)

        # Mock simnode for z1 start
        with patch("server.blueprints.admin.simnode_start_race") as mock_start:
            mock_start.return_value = {"stream_ws_url": "ws://mock"}

            resp1 = client.post("/api/admin/zones/z1/start-race", headers=admin_auth)
            assert resp1.status_code == 200

        # Verify z2 can still be set up (not blocked by z1 running)
        resp2 = client.post("/api/admin/zones/z2/set-session", json={
            "session_type": "qualifying",
            "session_id": "z2_qual_2",
            "team_ids": ["t5", "t6"],
            "total_laps": 3
        }, headers=admin_auth)
        assert resp2.status_code == 200


class TestZoneTeamIsolation:
    """G1-3: Teams in different zones are isolated."""

    def test_team_standings_per_zone(self, client, admin_auth):
        """Standings should be zone-specific."""
        resp1 = client.get("/api/admin/zones/z1/standings", headers=admin_auth)
        resp2 = client.get("/api/admin/zones/z2/standings", headers=admin_auth)

        assert resp1.status_code == 200
        assert resp2.status_code == 200


class TestZoneBracketIsolation:
    """G1-4: Brackets are zone-specific."""

    def test_bracket_per_zone(self, client, admin_auth):
        """Bracket should be computed per zone."""
        resp1 = client.get("/api/admin/zones/z1/bracket", headers=admin_auth)
        resp2 = client.get("/api/admin/zones/z2/bracket", headers=admin_auth)

        assert resp1.status_code == 200
        assert resp2.status_code == 200

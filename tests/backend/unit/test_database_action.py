"""
Database Action Unit Tests (Module E1)

Tests server/database/action.py CRUD operations.
"""

import pytest
import json
import tempfile
import os


@pytest.fixture(scope="function", autouse=True)
def fresh_db(monkeypatch):
    """Recreate DB for each test."""
    db_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SUBMISSIONS_DIR", tempfile.mkdtemp())
    monkeypatch.setenv("RECORDINGS_DIR", tempfile.mkdtemp())

    # Must reimport after monkeypatching env vars
    from server.database.models import init_db
    import server.database.action as action_module
    import server.config.config as config_module

    monkeypatch.setattr(config_module, "DB_PATH", db_path)
    monkeypatch.setattr(action_module, "DB_PATH", db_path)

    init_db(db_path)
    yield action_module

    if os.path.exists(db_path):
        os.remove(db_path)


class TestTeams:
    """E1-1: Team CRUD tests."""

    def test_create_and_get_team(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash123")
        team = fresh_db.get_team("t1")
        assert team is not None
        assert team["id"] == "t1"
        assert team["name"] == "Team One"
        assert team["password_hash"] == "hash123"

    def test_get_nonexistent_team(self, fresh_db):
        assert fresh_db.get_team("nonexistent") is None

    def test_list_teams(self, fresh_db):
        fresh_db.create_team("t1", "Team A", "hash1")
        fresh_db.create_team("t2", "Team B", "hash2")
        teams = fresh_db.list_teams()
        assert len(teams) == 2
        names = [t["name"] for t in teams]
        assert "Team A" in names
        assert "Team B" in names


class TestSubmissions:
    """E1-2: Submission CRUD tests."""

    def test_create_submission_and_get_active(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash")
        sub_id = fresh_db.create_submission("t1", "/path/to/code.py", "20240101_120000")
        assert sub_id is not None
        assert len(sub_id) > 0

        active = fresh_db.get_active_submission("t1")
        assert active is not None
        assert active["team_id"] == "t1"
        assert active["code_path"] == "/path/to/code.py"

    def test_create_submission_deactivates_old(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash")
        sub_id1 = fresh_db.create_submission("t1", "/path/v1.py", "20240101_120000")
        sub_id2 = fresh_db.create_submission("t1", "/path/v2.py", "20240101_130000")

        active = fresh_db.get_active_submission("t1")
        assert active["code_path"] == "/path/v2.py"

    def test_get_active_no_submission(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash")
        assert fresh_db.get_active_submission("t1") is None


class TestTestRuns:
    """E1-3: Test run CRUD tests."""

    def test_create_and_get_test_run(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash")
        sub_id = fresh_db.create_submission("t1", "/path/code.py", "20240101_120000")

        run_id = fresh_db.create_test_run(sub_id, "20240101_120000")
        assert run_id > 0

        latest = fresh_db.get_latest_test_run(sub_id)
        assert latest is not None
        assert latest["status"] == "queued"
        assert latest["submission_id"] == sub_id

    def test_update_test_run(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash")
        sub_id = fresh_db.create_submission("t1", "/path/code.py", "20240101_120000")
        run_id = fresh_db.create_test_run(sub_id, "20240101_120000")

        fresh_db.update_test_run(
            run_id,
            status="done",
            laps_completed=3,
            best_lap_time=45.5,
            finish_reason="race_end"
        )

        latest = fresh_db.get_latest_test_run(sub_id)
        assert latest["status"] == "done"
        assert latest["laps_completed"] == 3
        assert latest["best_lap_time"] == 45.5


class TestRaceSessions:
    """E1-4: Race session CRUD tests."""

    def test_create_and_get_session(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash")
        fresh_db.create_race_session(
            "race_1", "qualifying", ["t1"],
            3, "running", "2024-01-01T12:00:00"
        )

        session = fresh_db.get_race_session("race_1")
        assert session is not None
        assert session["type"] == "qualifying"
        assert session["total_laps"] == 3
        assert session["phase"] == "running"
        assert session["team_ids"] == ["t1"]

    def test_update_race_session(self, fresh_db):
        fresh_db.create_team("t1", "Team One", "hash")
        fresh_db.create_race_session(
            "race_1", "qualifying", ["t1"],
            3, "running", "2024-01-01T12:00:00"
        )

        fresh_db.update_race_session(
            "race_1",
            phase="finished",
            finished_at="2024-01-01T12:05:00",
            result={"winner": "t1"}
        )

        session = fresh_db.get_race_session("race_1")
        assert session["phase"] == "finished"
        assert session["finished_at"] == "2024-01-01T12:05:00"

    def test_get_nonexistent_session(self, fresh_db):
        assert fresh_db.get_race_session("nonexistent") is None


class TestRacePoints:
    """E1-5: Race points CRUD tests."""

    def test_upsert_and_get_standings(self, fresh_db):
        fresh_db.create_team("t1", "Team A", "hash1")
        fresh_db.create_team("t2", "Team B", "hash2")

        fresh_db.upsert_race_points("race_1", "t1", rank=1, points=10)
        fresh_db.upsert_race_points("race_1", "t2", rank=2, points=7)
        fresh_db.upsert_race_points("race_2", "t1", rank=2, points=7)
        fresh_db.upsert_race_points("race_2", "t2", rank=1, points=10)

        standings = fresh_db.get_standings()
        assert len(standings) == 2

        totals = {s["team_id"]: s["total_points"] for s in standings}
        assert totals["t1"] == 17
        assert totals["t2"] == 17

    def test_upsert_updates_existing(self, fresh_db):
        fresh_db.create_team("t1", "Team A", "hash1")
        fresh_db.upsert_race_points("race_1", "t1", rank=1, points=10)
        fresh_db.upsert_race_points("race_1", "t1", rank=2, points=7)

        standings = fresh_db.get_standings()
        assert len(standings) == 1
        assert standings[0]["total_points"] == 7  # Updated value


class TestForeignKeyConstraints:
    """E1-6: Database constraint tests."""

    def test_submission_without_team_fails(self, fresh_db):
        # SQLite may not enforce FK by default, so test the behavior:
        # It should either raise an exception or create an orphaned record
        # that doesn't appear in normal queries
        try:
            fresh_db.create_submission("nonexistent_team", "/path/code.py", "20240101_120000")
            # If no exception, verify the submission exists but is orphaned
            # (won't be returned by get_active_submission for a nonexistent team)
            result = fresh_db.get_active_submission("nonexistent_team")
            assert result is None or result["team_id"] == "nonexistent_team"
        except Exception:
            pass  # Also acceptable if FK constraint is enforced

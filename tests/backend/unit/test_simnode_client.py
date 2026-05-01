"""
Simnode Client Unit Tests (Module D1)

Tests server/utils/simnode_client.py HTTP client functions.
"""

import pytest
from unittest.mock import patch, Mock
import httpx


class TestStartRace:
    """D1-1: Tests for start_race()."""

    def test_start_race_success(self):
        with patch("server.utils.simnode_client.httpx.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: {
                    "status": "started",
                    "race_id": "qual_1",
                    "stream_ws_url": "ws://localhost:5001/race/qual_1/stream"
                }
            )
            from server.utils.simnode_client import start_race
            result = start_race(
                race_id="qual_1",
                session_type="qualifying",
                total_laps=3,
                cars=[{"car_slot": "car_1", "team_id": "t1", "team_name": "Team 1", "code_b64": "dGVzdA=="}]
            )
            assert result["status"] == "started"
            assert result["race_id"] == "qual_1"
            assert "stream_ws_url" in result

    def test_start_race_http_error(self):
        with patch("server.utils.simnode_client.httpx.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=500,
                text="Internal Server Error",
                raise_for_status=Mock(side_effect=httpx.HTTPStatusError(
                    "Server Error", request=Mock(), response=Mock(status_code=500)
                ))
            )
            from server.utils.simnode_client import start_race
            with pytest.raises(RuntimeError, match="Sim Node"):
                start_race("race_1", "qualifying", 3, [])

    def test_start_race_timeout(self):
        with patch("server.utils.simnode_client.httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Connection timed out")
            from server.utils.simnode_client import start_race
            with pytest.raises(RuntimeError, match="无法连接"):
                start_race("race_1", "qualifying", 3, [])

    def test_start_race_connection_error(self):
        with patch("server.utils.simnode_client.httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("Cannot connect")
            from server.utils.simnode_client import start_race
            with pytest.raises(RuntimeError, match="无法连接"):
                start_race("race_1", "qualifying", 3, [])


class TestCancelRace:
    """D1-2: Tests for cancel_race()."""

    def test_cancel_race_success(self):
        with patch("server.utils.simnode_client.httpx.post") as mock_post:
            mock_post.return_value = Mock(status_code=200)
            from server.utils.simnode_client import cancel_race
            assert cancel_race("qual_1") is True

    def test_cancel_race_failure(self):
        with patch("server.utils.simnode_client.httpx.post") as mock_post:
            mock_post.return_value = Mock(status_code=500)
            from server.utils.simnode_client import cancel_race
            assert cancel_race("qual_1") is False

    def test_cancel_race_exception(self):
        with patch("server.utils.simnode_client.httpx.post") as mock_post:
            mock_post.side_effect = Exception("Network error")
            from server.utils.simnode_client import cancel_race
            assert cancel_race("qual_1") is False


class TestGetRaceStatus:
    """D1-3: Tests for get_race_status()."""

    def test_get_status_running(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: {"race_id": "qual_1", "status": "running"}
            )
            from server.utils.simnode_client import get_race_status
            assert get_race_status("qual_1") == "running"

    def test_get_status_not_found(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(status_code=404)
            from server.utils.simnode_client import get_race_status
            assert get_race_status("qual_1") is None

    def test_get_status_exception(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            from server.utils.simnode_client import get_race_status
            assert get_race_status("qual_1") is None


class TestGetRaceResult:
    """D1-4: Tests for get_race_result()."""

    def test_get_result_success(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: {
                    "race_id": "qual_1",
                    "final_rankings": [
                        {"rank": 1, "team_id": "t1", "total_time": 120.5, "laps_completed": 3},
                    ],
                    "finish_reason": "race_end"
                }
            )
            from server.utils.simnode_client import get_race_result
            result = get_race_result("qual_1")
            assert len(result["final_rankings"]) == 1
            assert result["final_rankings"][0]["team_id"] == "t1"

    def test_get_result_not_ready(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(status_code=425)
            from server.utils.simnode_client import get_race_result
            assert get_race_result("qual_1") is None

    def test_get_result_not_found(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(status_code=404)
            from server.utils.simnode_client import get_race_result
            assert get_race_result("qual_1") is None


class TestGetRaceLiveInfo:
    """D1-5: Tests for get_race_live_info()."""

    def test_get_live_info_success(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: {
                    "webots_pid": 12345,
                    "sim_time": 45.3,
                    "cars": [{"team_id": "t1", "x": 10.0, "y": 5.0}]
                }
            )
            from server.utils.simnode_client import get_race_live_info
            result = get_race_live_info("qual_1")
            assert result["webots_pid"] == 12345
            assert result["sim_time"] == 45.3

    def test_get_live_info_not_found(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(status_code=404)
            from server.utils.simnode_client import get_race_live_info
            assert get_race_live_info("qual_1") is None


class TestListRaces:
    """D1-6: Tests for list_races()."""

    def test_list_races_success(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.return_value = Mock(
                status_code=200,
                json=lambda: [
                    {"race_id": "qual_1", "status": "running"},
                    {"race_id": "test_1", "status": "completed"}
                ]
            )
            from server.utils.simnode_client import list_races
            result = list_races()
            assert len(result) == 2
            assert result[0] == ("qual_1", "running")

    def test_list_races_exception(self):
        with patch("server.utils.simnode_client.httpx.get") as mock_get:
            mock_get.side_effect = Exception("Network error")
            from server.utils.simnode_client import list_races
            assert list_races() == []

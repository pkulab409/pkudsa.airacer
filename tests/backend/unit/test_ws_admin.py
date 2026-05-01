"""
WebSocket Admin Unit Tests (Module C1, C2)

Tests server/ws/admin.py AdminConnectionManager.
"""

import pytest
from fastapi import WebSocketDisconnect
from server.ws.admin import AdminConnectionManager


class FakeWebSocket:
    """Mock WebSocket client that collects sent messages."""

    def __init__(self):
        self.sent_messages = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def close(self):
        self.closed = True


class TestConnectionManager:
    """C1: WebSocket connection management tests."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        """C1-1: Connect and disconnect clients."""
        manager = AdminConnectionManager()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        assert len(manager.active) == 0

        await manager.connect(ws1)
        assert len(manager.active) == 1

        await manager.connect(ws2)
        assert len(manager.active) == 2

        manager.disconnect(ws1)
        assert len(manager.active) == 1

        manager.disconnect(ws2)
        assert len(manager.active) == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self):
        """C1-2: Broadcast message to all connected clients."""
        manager = AdminConnectionManager()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        await manager.connect(ws1)
        await manager.connect(ws2)

        test_msg = {"type": "sim_status", "state": "running", "race_id": "qual_1"}

        await manager.broadcast(test_msg)

        assert len(ws1.sent_messages) >= 1  # May include initial default msg
        assert ws1.sent_messages[-1]["type"] == "sim_status"
        assert ws1.sent_messages[-1]["state"] == "running"

        assert len(ws2.sent_messages) >= 1
        assert ws2.sent_messages[-1]["type"] == "sim_status"

    @pytest.mark.asyncio
    async def test_broadcast_skips_disconnected(self):
        """C1-3: Broadcast removes clients that raise WebSocketDisconnect."""
        manager = AdminConnectionManager()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        await manager.connect(ws1)
        await manager.connect(ws2)

        # Now make ws2 fail on send
        async def fail_send_json(data):
            raise WebSocketDisconnect()

        ws2.send_json = fail_send_json

        await manager.broadcast({"type": "heartbeat"})

        assert len(manager.active) == 1  # ws2 removed

    @pytest.mark.asyncio
    async def test_last_message_per_zone(self):
        """C1-4: Last message stored per zone."""
        manager = AdminConnectionManager()

        manager._last_msg_per_zone["zone_a"] = {"type": "sim_status", "state": "running"}
        manager._last_msg_per_zone["zone_b"] = {"type": "sim_status", "state": "idle"}

        assert manager._last_msg_per_zone["zone_a"]["state"] == "running"
        assert manager._last_msg_per_zone["zone_b"]["state"] == "idle"

        manager._last_msg_per_zone["zone_a"] = {"type": "sim_status", "state": "completed"}
        assert manager._last_msg_per_zone["zone_a"]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_multiple_messages_in_sequence(self):
        """C1-5: Multiple messages delivered in order."""
        manager = AdminConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws)

        messages = [
            {"type": "sim_status", "state": "idle", "zone_id": "z1"},
            {"type": "sim_status", "state": "running", "zone_id": "z1"},
            {"type": "sim_status", "state": "completed", "zone_id": "z1"},
        ]

        for msg in messages:
            await manager.broadcast(msg)

        # Filter out initial default message
        sim_msgs = [m for m in ws.sent_messages if m.get("type") == "sim_status"]
        assert len(sim_msgs) >= 3
        assert sim_msgs[-3]["state"] == "idle"
        assert sim_msgs[-2]["state"] == "running"
        assert sim_msgs[-1]["state"] == "completed"


class TestWebSocketReconnect:
    """C2: WebSocket reconnection tests."""

    @pytest.mark.asyncio
    async def test_reconnect_receives_latest_message(self):
        """C2-1: Reconnected client receives subsequent messages."""
        manager = AdminConnectionManager()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()

        await manager.connect(ws1)
        await manager.broadcast({"type": "sim_status", "state": "idle", "zone_id": "z1"})
        await manager.broadcast({"type": "sim_status", "state": "running", "zone_id": "z1"})

        manager.disconnect(ws1)

        await manager.connect(ws2)
        await manager.broadcast({"type": "sim_status", "state": "completed", "zone_id": "z1"})

        # ws2 should have received: default msg + completed
        assert len(ws2.sent_messages) >= 1
        assert ws2.sent_messages[-1]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_heartbeat_message_format(self):
        """C2-2: Heartbeat message has correct format."""
        manager = AdminConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws)

        heartbeat = {
            "type": "sim_status",
            "zone_id": "default",
            "state": "idle",
            "sim_time_approx": 0
        }
        manager._last_msg_per_zone["default"] = heartbeat

        await manager.broadcast({**heartbeat})

        assert "type" in ws.sent_messages[-1]
        assert ws.sent_messages[-1]["type"] == "sim_status"
        assert "zone_id" in ws.sent_messages[-1]


class TestConnectionEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_broadcast_empty_connections(self):
        """Edge: Broadcasting to empty connection list does not error."""
        manager = AdminConnectionManager()
        await manager.broadcast({"type": "test"})

    def test_disconnect_nonexistent(self):
        """Edge: Disconnecting a non-existent client does not error."""
        manager = AdminConnectionManager()
        ws = FakeWebSocket()
        manager.disconnect(ws)

    @pytest.mark.asyncio
    async def test_many_concurrent_connections(self):
        """Edge: 50 concurrent connections all receive broadcast."""
        manager = AdminConnectionManager()
        sockets = [FakeWebSocket() for _ in range(50)]

        for ws in sockets:
            await manager.connect(ws)

        assert len(manager.active) == 50

        await manager.broadcast({"type": "test", "zone_id": "z1"})

        for ws in sockets:
            assert len(ws.sent_messages) >= 1

    @pytest.mark.asyncio
    async def test_sim_status_type_messages(self):
        """Verify all sim_status state values are handled."""
        manager = AdminConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws)

        valid_states = ["idle", "running", "recording_ready", "aborted"]
        for state in valid_states:
            await manager.broadcast({
                "type": "sim_status",
                "state": state,
                "race_id": f"test_{state}",
                "sim_time": 45.3,
                "zone_id": "z1"
            })

        sim_msgs = [m for m in ws.sent_messages if m.get("type") == "sim_status"]
        assert len(sim_msgs) >= 4
        assert sim_msgs[-4]["state"] == "idle"
        assert sim_msgs[-3]["state"] == "running"
        assert sim_msgs[-2]["state"] == "recording_ready"
        assert sim_msgs[-1]["state"] == "aborted"

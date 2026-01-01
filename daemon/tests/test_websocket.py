"""Tests for WebSocket server functionality."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from wormhole.daemon import WormholeDaemon
from wormhole.protocol import (
    EventMessage,
    HelloMessage,
    InputMessage,
    PermissionResponseMessage,
    SubscribeMessage,
    SyncMessage,
)


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self) -> None:
        self.sent_messages: list[str] = []
        self.incoming_messages: asyncio.Queue[str] = asyncio.Queue()
        self._closed = False

    async def send(self, data: str) -> None:
        if not self._closed:
            self.sent_messages.append(data)

    async def recv(self) -> str:
        return await self.incoming_messages.get()

    async def close(self) -> None:
        self._closed = True

    def __aiter__(self) -> "MockWebSocket":
        return self

    async def __anext__(self) -> str:
        if self._closed:
            raise StopAsyncIteration
        try:
            msg = await asyncio.wait_for(self.incoming_messages.get(), timeout=0.1)
            return msg
        except TimeoutError:
            raise StopAsyncIteration from None

    def queue_message(self, msg: str) -> None:
        """Queue a message to be received."""
        self.incoming_messages.put_nowait(msg)


class TestWebSocketHandshake:
    """Tests for WebSocket handshake (hello/welcome)."""

    @pytest.mark.asyncio
    async def test_hello_receives_welcome(self) -> None:
        daemon = WormholeDaemon(port=7117)
        ws = MockWebSocket()

        # Queue hello message
        hello = HelloMessage(client_version="1.0.0", device_name="Test iPhone")
        ws.queue_message(hello.model_dump_json())

        # Handle connection (runs until no more messages)
        await daemon._handle_connection(ws)

        # Verify welcome was sent
        assert len(ws.sent_messages) == 1
        welcome = json.loads(ws.sent_messages[0])
        assert welcome["type"] == "welcome"
        assert welcome["server_version"] == "0.1.0"
        assert "machine_name" in welcome
        assert "sessions" in welcome

    @pytest.mark.asyncio
    async def test_welcome_includes_session_list(self, tmp_path: Path) -> None:
        daemon = WormholeDaemon(port=7117)

        # Create a session
        daemon.create_session("test-session", tmp_path)

        ws = MockWebSocket()
        hello = HelloMessage(client_version="1.0.0", device_name="Test iPhone")
        ws.queue_message(hello.model_dump_json())

        await daemon._handle_connection(ws)

        welcome = json.loads(ws.sent_messages[0])
        assert len(welcome["sessions"]) == 1
        assert welcome["sessions"][0]["name"] == "test-session"
        assert welcome["sessions"][0]["state"] == "idle"


class TestEventStreaming:
    """Tests for streaming events to subscribed clients."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self) -> None:
        daemon = WormholeDaemon(port=7117)

        # Add mock clients
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        daemon._clients.add(ws1)
        daemon._clients.add(ws2)

        # Create an event message
        from datetime import datetime

        event = EventMessage(
            session="test",
            sequence=1,
            timestamp=datetime.now(),
            message={"type": "test"},
        )

        await daemon._broadcast(event)

        # Both clients should have received the message
        assert len(ws1.sent_messages) == 1
        assert len(ws2.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_broadcast_handles_disconnected_clients(self) -> None:
        daemon = WormholeDaemon(port=7117)

        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        ws2._closed = True  # Simulate disconnected client

        daemon._clients.add(ws1)
        daemon._clients.add(ws2)

        from datetime import datetime

        event = EventMessage(
            session="test",
            sequence=1,
            timestamp=datetime.now(),
            message={"type": "test"},
        )

        # Should not raise
        await daemon._broadcast(event)

        assert len(ws1.sent_messages) == 1


class TestSubscriptions:
    """Tests for session subscription handling."""

    @pytest.mark.asyncio
    async def test_subscribe_to_specific_sessions(self, tmp_path: Path) -> None:
        daemon = WormholeDaemon(port=7117)
        daemon.create_session("session-a", tmp_path / "a")
        daemon.create_session("session-b", tmp_path / "b")

        ws = MockWebSocket()
        subscribed: set[str] = set()

        # Test subscribe to specific session
        msg = SubscribeMessage(sessions=["session-a"])
        await daemon._handle_message(ws, msg, subscribed)

        assert "session-a" in subscribed
        assert "session-b" not in subscribed

    @pytest.mark.asyncio
    async def test_subscribe_to_all_sessions(self, tmp_path: Path) -> None:
        daemon = WormholeDaemon(port=7117)
        daemon.create_session("session-a", tmp_path / "a")
        daemon.create_session("session-b", tmp_path / "b")

        ws = MockWebSocket()
        subscribed: set[str] = set()

        msg = SubscribeMessage(sessions="*")
        await daemon._handle_message(ws, msg, subscribed)

        assert "session-a" in subscribed
        assert "session-b" in subscribed


class TestPermissionResponseRouting:
    """Tests for routing permission responses to sessions."""

    @pytest.mark.asyncio
    async def test_permission_response_routes_to_correct_session(
        self, tmp_path: Path
    ) -> None:
        daemon = WormholeDaemon(port=7117)
        session = daemon.create_session("test", tmp_path)

        # Create a pending permission in the session
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        request_id = "test-request-123"
        session._pending_permissions[request_id] = future

        ws = MockWebSocket()
        subscribed: set[str] = set()

        # Send permission response
        msg = PermissionResponseMessage(
            request_id=request_id,
            decision="allow",
        )
        await daemon._handle_message(ws, msg, subscribed)

        # Future should be resolved
        assert future.done()
        assert future.result() == "allow"


class TestInputHandling:
    """Tests for handling input messages from phone."""

    @pytest.mark.asyncio
    async def test_input_message_calls_session_query(self, tmp_path: Path) -> None:
        daemon = WormholeDaemon(port=7117)
        session = daemon.create_session("test", tmp_path)

        # Mock the client
        mock_client = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.receive_response = MagicMock(return_value=iter([]))
        session._client = mock_client

        ws = MockWebSocket()
        subscribed: set[str] = set()

        msg = InputMessage(session="test", text="Hello Claude")
        await daemon._handle_message(ws, msg, subscribed)

        mock_client.query.assert_called_once_with("Hello Claude")


class TestControlMessages:
    """Tests for control message handling."""

    @pytest.mark.asyncio
    async def test_interrupt_calls_session_interrupt(self, tmp_path: Path) -> None:
        daemon = WormholeDaemon(port=7117)
        session = daemon.create_session("test", tmp_path)

        mock_client = AsyncMock()
        session._client = mock_client

        ws = MockWebSocket()
        subscribed: set[str] = set()

        from wormhole.protocol import ControlMessage

        msg = ControlMessage(session="test", action="interrupt")
        await daemon._handle_message(ws, msg, subscribed)

        mock_client.interrupt.assert_called_once()


class TestSyncMessages:
    """Tests for sync message handling."""

    @pytest.mark.asyncio
    async def test_sync_returns_events_since_sequence(self, tmp_path: Path) -> None:
        daemon = WormholeDaemon(port=7117)
        session = daemon.create_session("test", tmp_path)

        # Add some events to the session
        for i in range(5):
            await session._handle_sdk_message({"type": "test", "index": i})

        ws = MockWebSocket()
        subscribed: set[str] = set()

        msg = SyncMessage(session="test", last_seen_sequence=3)
        await daemon._handle_message(ws, msg, subscribed)

        assert len(ws.sent_messages) == 1
        response = json.loads(ws.sent_messages[0])
        assert response["type"] == "sync_response"
        assert response["session"] == "test"
        assert len(response["events"]) == 2  # Events 4 and 5


class TestErrorHandling:
    """Tests for error handling in WebSocket messages."""

    @pytest.mark.asyncio
    async def test_invalid_message_returns_error(self) -> None:
        daemon = WormholeDaemon(port=7117)
        ws = MockWebSocket()

        # Queue invalid JSON
        ws.queue_message("not valid json")

        await daemon._handle_connection(ws)

        # Should have received error message
        assert len(ws.sent_messages) == 1
        error = json.loads(ws.sent_messages[0])
        assert error["type"] == "error"
        assert error["code"] == "INVALID_MESSAGE"

    @pytest.mark.asyncio
    async def test_unknown_message_type_returns_error(self) -> None:
        daemon = WormholeDaemon(port=7117)
        ws = MockWebSocket()

        # Queue unknown message type
        ws.queue_message(json.dumps({"type": "unknown_type"}))

        await daemon._handle_connection(ws)

        assert len(ws.sent_messages) == 1
        error = json.loads(ws.sent_messages[0])
        assert error["type"] == "error"
        assert "Unknown message type" in error["message"]

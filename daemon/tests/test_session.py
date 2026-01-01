"""Tests for WormholeSession."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wormhole.session import SessionState, WormholeSession


class TestSessionCreation:
    """Tests for session creation."""

    def test_creates_with_correct_state(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)
        assert session.name == "test"
        assert session.directory == tmp_path
        assert session.state == SessionState.IDLE
        assert session.claude_session_id is None
        assert session.cost_usd == 0.0

    def test_event_buffer_empty_initially(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)
        events = session.get_events_since(0)
        assert events == []

    def test_custom_buffer_size(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path, buffer_size=50)
        assert session.buffer_size == 50


class TestEventBuffering:
    """Tests for event buffering."""

    @pytest.mark.asyncio
    async def test_buffer_respects_max_size(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path, buffer_size=5)

        # Simulate adding events via internal method
        for i in range(10):
            await session._handle_sdk_message({"type": "test", "index": i})

        # Buffer should only have last 5 events
        events = session.get_events_since(0)
        assert len(events) == 5
        # Verify they're the last 5
        assert events[0].message["index"] == 5
        assert events[-1].message["index"] == 9

    @pytest.mark.asyncio
    async def test_get_events_since_sequence(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path, buffer_size=100)

        for i in range(5):
            await session._handle_sdk_message({"type": "test", "index": i})

        # Get events since sequence 3
        events = session.get_events_since(3)
        assert len(events) == 2
        assert events[0].sequence == 4
        assert events[1].sequence == 5

    @pytest.mark.asyncio
    async def test_events_have_correct_timestamps(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)

        await session._handle_sdk_message({"type": "test"})
        events = session.get_events_since(0)

        assert len(events) == 1
        assert events[0].timestamp is not None
        assert events[0].sequence == 1


class TestSDKMessageHandling:
    """Tests for handling SDK messages."""

    @pytest.mark.asyncio
    async def test_captures_session_id_from_init(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)

        # SDK SystemMessage structure
        await session._handle_sdk_message({
            "subtype": "init",
            "data": {
                "session_id": "abc-123-def",
                "cwd": str(tmp_path),
                "tools": ["Bash", "Read"],
            }
        })

        assert session.claude_session_id == "abc-123-def"

    @pytest.mark.asyncio
    async def test_updates_cost_from_result(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)

        await session._handle_sdk_message({
            "subtype": "success",
            "total_cost_usd": 0.0234,
            "session_id": "abc",
        })

        assert session.cost_usd == 0.0234

    @pytest.mark.asyncio
    async def test_broadcasts_events(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)

        received_messages: list[Any] = []

        async def capture_broadcast(msg: Any) -> None:
            received_messages.append(msg)

        session.set_broadcast_callback(capture_broadcast)

        await session._handle_sdk_message({"type": "test", "data": "value"})

        assert len(received_messages) == 1
        assert received_messages[0].session == "test"
        assert received_messages[0].sequence == 1

    @pytest.mark.asyncio
    async def test_handles_dataclass_messages(self, tmp_path: Path) -> None:
        """Test that SDK dataclass messages are properly converted."""
        session = WormholeSession(name="test", directory=tmp_path)

        @dataclass
        class MockSDKMessage:
            subtype: str
            data: dict[str, Any]

        msg = MockSDKMessage(subtype="init", data={"session_id": "test-123"})
        await session._handle_sdk_message(msg)

        assert session.claude_session_id == "test-123"


class TestPermissionHandling:
    """Tests for permission request/response."""

    def test_respond_to_unknown_request_returns_false(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)
        result = session.respond_to_permission("nonexistent", "allow")
        assert result is False

    @pytest.mark.asyncio
    async def test_permission_callback_blocks_until_response(self, tmp_path: Path) -> None:
        """Verify can_use_tool blocks until permission response received."""
        session = WormholeSession(name="test", directory=tmp_path)

        received_requests: list[Any] = []

        async def capture_broadcast(msg: Any) -> None:
            received_requests.append(msg)

        session.set_broadcast_callback(capture_broadcast)

        # Mock the context
        mock_context = MagicMock()

        # Start permission request in background
        async def request_permission() -> Any:
            return await session._permission_handler(
                "Write",
                {"file_path": "test.py", "content": "hello"},
                mock_context,
            )

        task = asyncio.create_task(request_permission())

        # Wait a bit for the request to be registered
        await asyncio.sleep(0.01)

        # Verify state changed
        assert session.state == SessionState.AWAITING_APPROVAL

        # Verify request was broadcast
        assert len(received_requests) == 1
        request_id = received_requests[0].request_id

        # Respond to permission
        assert session.respond_to_permission(request_id, "allow") is True

        # Wait for result
        result = await task

        # Verify state changed back
        assert session.state == SessionState.WORKING

        # Verify result is PermissionResultAllow
        assert result.behavior == "allow"

    @pytest.mark.asyncio
    async def test_permission_deny_returns_correct_result(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)

        received_requests: list[Any] = []

        async def capture_broadcast(msg: Any) -> None:
            received_requests.append(msg)

        session.set_broadcast_callback(capture_broadcast)
        mock_context = MagicMock()

        async def request_permission() -> Any:
            return await session._permission_handler(
                "Bash",
                {"command": "rm -rf /"},
                mock_context,
            )

        task = asyncio.create_task(request_permission())
        await asyncio.sleep(0.01)

        request_id = received_requests[0].request_id
        session.respond_to_permission(request_id, "deny")

        result = await task

        assert result.behavior == "deny"
        assert result.message == "User denied"
        assert result.interrupt is False

    @pytest.mark.asyncio
    async def test_multiple_concurrent_permissions(self, tmp_path: Path) -> None:
        """Test handling multiple permission requests concurrently."""
        session = WormholeSession(name="test", directory=tmp_path)

        received_requests: list[Any] = []

        async def capture_broadcast(msg: Any) -> None:
            received_requests.append(msg)

        session.set_broadcast_callback(capture_broadcast)
        mock_context = MagicMock()

        # Start two permission requests
        task1 = asyncio.create_task(
            session._permission_handler("Write", {"file": "a.py"}, mock_context)
        )
        await asyncio.sleep(0.01)

        task2 = asyncio.create_task(
            session._permission_handler("Bash", {"cmd": "ls"}, mock_context)
        )
        await asyncio.sleep(0.01)

        assert len(received_requests) == 2

        # Respond in reverse order
        session.respond_to_permission(received_requests[1].request_id, "allow")
        session.respond_to_permission(received_requests[0].request_id, "deny")

        result1 = await task1
        result2 = await task2

        assert result1.behavior == "deny"
        assert result2.behavior == "allow"


class TestSessionStateTransitions:
    """Test session state machine transitions."""

    def test_initial_state_is_idle(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)
        assert session.state == SessionState.IDLE

    @pytest.mark.asyncio
    async def test_query_changes_state_to_working(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)

        # Mock the client
        mock_client = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.receive_response = MagicMock(return_value=iter([]))
        session._client = mock_client

        await session.query("test prompt")

        assert session.state == SessionState.WORKING
        mock_client.query.assert_called_once_with("test prompt")

    @pytest.mark.asyncio
    async def test_stop_resets_state_to_idle(self, tmp_path: Path) -> None:
        session = WormholeSession(name="test", directory=tmp_path)
        session.state = SessionState.WORKING

        mock_client = AsyncMock()
        session._client = mock_client

        await session.stop()

        assert session.state == SessionState.IDLE
        assert session._client is None
        mock_client.disconnect.assert_called_once()

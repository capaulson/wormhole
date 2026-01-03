"""Tests for WormholeDaemon session management."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from wormhole.daemon import WormholeDaemon
from wormhole.persistence import EventPersistence, SessionPersistence


class TestSessionCreation:
    """Tests for creating sessions."""

    def test_create_session_returns_session(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        session = daemon.create_session("test-session", tmp_path)

        assert session is not None
        assert session.name == "test-session"
        assert session.directory == tmp_path.resolve()

    def test_create_session_registers_in_sessions_dict(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        daemon.create_session("test-session", tmp_path)

        assert "test-session" in daemon.sessions
        assert daemon.sessions["test-session"].name == "test-session"

    def test_create_session_registers_directory_mapping(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        daemon.create_session("test-session", tmp_path)

        assert tmp_path.resolve() in daemon.directory_to_session
        assert daemon.directory_to_session[tmp_path.resolve()] == "test-session"

    def test_create_session_sets_broadcast_callback(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        session = daemon.create_session("test-session", tmp_path)

        assert session._broadcast_callback is not None


class TestOneSessionPerDirectory:
    """Tests for one-session-per-directory constraint."""

    def test_duplicate_directory_raises_error(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        daemon.create_session("first-session", tmp_path)

        with pytest.raises(ValueError) as exc_info:
            daemon.create_session("second-session", tmp_path)

        assert "already exists" in str(exc_info.value)
        assert "first-session" in str(exc_info.value)

    def test_different_directories_allowed(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        session_a = daemon.create_session("session-a", dir_a)
        session_b = daemon.create_session("session-b", dir_b)

        assert session_a is not None
        assert session_b is not None
        assert len(daemon.sessions) == 2

    def test_resolves_relative_paths(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        # Create with explicit path
        daemon.create_session("first", tmp_path)

        # Try to create with same path but different form
        with pytest.raises(ValueError):
            daemon.create_session("second", tmp_path / "." / ".")


class TestSessionClosure:
    """Tests for closing sessions."""

    @pytest.mark.asyncio
    async def test_close_session_removes_from_registry(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        session = daemon.create_session("test-session", tmp_path)
        session._client = AsyncMock()  # Mock to avoid real SDK calls

        await daemon.close_session("test-session")

        assert "test-session" not in daemon.sessions
        assert tmp_path.resolve() not in daemon.directory_to_session

    @pytest.mark.asyncio
    async def test_close_session_stops_sdk_client(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        session = daemon.create_session("test-session", tmp_path)
        mock_client = AsyncMock()
        session._client = mock_client

        await daemon.close_session("test-session")

        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_nonexistent_session_no_error(self, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        # Should not raise
        await daemon.close_session("nonexistent")

    @pytest.mark.asyncio
    async def test_can_create_session_after_closing(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        session1 = daemon.create_session("test-session", tmp_path)
        session1._client = AsyncMock()

        await daemon.close_session("test-session")

        # Should be able to create new session in same directory
        session2 = daemon.create_session("new-session", tmp_path)
        assert session2 is not None


class TestMultipleSessions:
    """Tests for handling multiple concurrent sessions."""

    def test_multiple_sessions_tracked_independently(self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        dirs = [tmp_path / f"project{i}" for i in range(3)]
        for d in dirs:
            d.mkdir()

        sessions = [
            daemon.create_session(f"session-{i}", dirs[i]) for i in range(3)
        ]

        assert len(daemon.sessions) == 3
        assert len(daemon.directory_to_session) == 3

        # Verify each session has correct directory
        for i, session in enumerate(sessions):
            assert session.directory == dirs[i].resolve()

    @pytest.mark.asyncio
    async def test_session_broadcasts_routed_independently(
        self, tmp_path: Path, event_persistence: EventPersistence, session_persistence: SessionPersistence
    ) -> None:
        daemon = WormholeDaemon(port=7117, event_persistence=event_persistence, session_persistence=session_persistence)

        received_events: list[tuple[str, object]] = []

        async def capture_broadcast(msg: object) -> None:
            received_events.append((getattr(msg, "session", ""), msg))

        # Override daemon's broadcast BEFORE creating sessions
        daemon._broadcast = capture_broadcast  # type: ignore

        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        session_a = daemon.create_session("session-a", tmp_path / "a")
        session_b = daemon.create_session("session-b", tmp_path / "b")

        # Have both sessions emit events
        await session_a._handle_sdk_message({"type": "from_a"})
        await session_b._handle_sdk_message({"type": "from_b"})

        # Verify events are correctly attributed
        assert len(received_events) == 2
        assert received_events[0][0] == "session-a"
        assert received_events[1][0] == "session-b"


class TestDaemonInitialization:
    """Tests for daemon initialization."""

    def test_default_port(self, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(event_persistence=event_persistence, session_persistence=session_persistence)
        assert daemon.port == 7117

    def test_custom_port(self, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(port=8080, event_persistence=event_persistence, session_persistence=session_persistence)
        assert daemon.port == 8080

    def test_starts_with_empty_sessions(self, event_persistence: EventPersistence, session_persistence: SessionPersistence) -> None:
        daemon = WormholeDaemon(event_persistence=event_persistence, session_persistence=session_persistence)
        assert len(daemon.sessions) == 0
        assert len(daemon.directory_to_session) == 0
        assert len(daemon._clients) == 0

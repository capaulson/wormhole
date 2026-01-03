"""Pytest configuration and fixtures."""

from pathlib import Path
from typing import Any

import pytest

from wormhole.persistence import EventPersistence, SessionPersistence


@pytest.fixture
def event_persistence(tmp_path: Path) -> EventPersistence:
    """Create isolated event persistence for each test."""
    return EventPersistence(base_dir=tmp_path / "events")


@pytest.fixture
def session_persistence(tmp_path: Path) -> SessionPersistence:
    """Create isolated session persistence for each test."""
    return SessionPersistence(path=tmp_path / "sessions.json")


@pytest.fixture
def sample_system_init() -> dict[str, Any]:
    """Sample system init message from SDK."""
    return {
        "type": "system",
        "subtype": "init",
        "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "cwd": "/home/user/project",
        "tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        "model": "claude-sonnet-4-5",
        "permission_mode": "default",
    }


@pytest.fixture
def sample_assistant_message() -> dict[str, Any]:
    """Sample assistant message from SDK."""
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "I'll create the authentication module."},
                {
                    "type": "tool_use",
                    "id": "toolu_01ABC123",
                    "name": "Write",
                    "input": {
                        "file_path": "auth.py",
                        "content": "def authenticate(user, password):\n    pass\n",
                    },
                },
            ]
        },
    }


@pytest.fixture
def sample_result() -> dict[str, Any]:
    """Sample result message from SDK."""
    return {
        "type": "result",
        "subtype": "success",
        "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "total_cost_usd": 0.0234,
        "usage": {"input_tokens": 1234, "output_tokens": 567},
    }

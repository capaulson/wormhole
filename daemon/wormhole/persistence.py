"""Session persistence for daemon restarts."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PersistedSession(BaseModel):
    """Minimal session info for persistence."""
    name: str
    directory: str
    claude_session_id: str | None = None
    cost_usd: float = 0.0
    created_at: datetime = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "name": self.name,
            "directory": self.directory,
            "claude_session_id": self.claude_session_id,
            "cost_usd": self.cost_usd,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersistedSession:
        """Create from dict."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            name=data["name"],
            directory=data["directory"],
            claude_session_id=data.get("claude_session_id"),
            cost_usd=data.get("cost_usd", 0.0),
            created_at=created_at or datetime.now(),
        )


class SessionPersistence:
    """Manages session persistence to disk."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".local/share/wormhole/sessions.json"

    def _ensure_dir(self) -> None:
        """Ensure the parent directory exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_sessions(self) -> list[PersistedSession]:
        """Load all persisted sessions."""
        if not self.path.exists():
            return []

        try:
            with open(self.path) as f:
                data = json.load(f)

            sessions = []
            for item in data.get("sessions", []):
                try:
                    sessions.append(PersistedSession.from_dict(item))
                except Exception as e:
                    logger.warning(f"Failed to load session: {e}")
            return sessions
        except Exception as e:
            logger.error(f"Failed to load sessions from {self.path}: {e}")
            return []

    def save_sessions(self, sessions: list[PersistedSession]) -> None:
        """Save all sessions to disk."""
        self._ensure_dir()
        try:
            data = {
                "version": 1,
                "sessions": [s.to_dict() for s in sessions],
            }
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(sessions)} sessions to {self.path}")
        except Exception as e:
            logger.error(f"Failed to save sessions to {self.path}: {e}")

    def add_session(self, session: PersistedSession) -> None:
        """Add or update a session."""
        sessions = self.load_sessions()
        # Update if exists, otherwise append
        for i, s in enumerate(sessions):
            if s.name == session.name:
                sessions[i] = session
                self.save_sessions(sessions)
                return
        sessions.append(session)
        self.save_sessions(sessions)

    def remove_session(self, name: str) -> None:
        """Remove a session by name."""
        sessions = self.load_sessions()
        sessions = [s for s in sessions if s.name != name]
        self.save_sessions(sessions)

    def update_session(self, name: str, **updates: Any) -> None:
        """Update specific fields of a session."""
        sessions = self.load_sessions()
        for i, s in enumerate(sessions):
            if s.name == name:
                data = s.to_dict()
                data.update(updates)
                sessions[i] = PersistedSession.from_dict(data)
                self.save_sessions(sessions)
                return
        logger.warning(f"Session not found for update: {name}")

    def clear(self) -> None:
        """Remove all persisted sessions."""
        if self.path.exists():
            self.path.unlink()


class PersistedEvent(BaseModel):
    """A persisted event from a session."""
    sequence: int
    timestamp: datetime
    message: dict[str, Any]

    def to_json_line(self) -> str:
        """Convert to a single JSON line."""
        return json.dumps({
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
        })

    @classmethod
    def from_json_line(cls, line: str) -> PersistedEvent:
        """Create from a JSON line."""
        data = json.loads(line)
        return cls(
            sequence=data["sequence"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            message=data["message"],
        )


class EventPersistence:
    """Manages event persistence to disk using JSONL format.

    Events are stored in ~/.local/share/wormhole/events/{session_name}.jsonl
    One JSON object per line for efficient appending and reading.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.home() / ".local/share/wormhole/events"

    def _ensure_dir(self) -> None:
        """Ensure the events directory exists."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_event_file(self, session_name: str) -> Path:
        """Get the event file path for a session."""
        # Sanitize session name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
        return self.base_dir / f"{safe_name}.jsonl"

    def append_event(self, session_name: str, event: PersistedEvent) -> None:
        """Append a single event to the session's event file."""
        self._ensure_dir()
        event_file = self._get_event_file(session_name)
        try:
            with open(event_file, "a") as f:
                f.write(event.to_json_line() + "\n")
        except Exception as e:
            logger.error(f"Failed to append event to {event_file}: {e}")

    def load_events(self, session_name: str, since_sequence: int = 0) -> list[PersistedEvent]:
        """Load events for a session, optionally filtering by sequence.

        Args:
            session_name: The session to load events for
            since_sequence: Only return events with sequence > since_sequence

        Returns:
            List of events ordered by sequence
        """
        event_file = self._get_event_file(session_name)
        if not event_file.exists():
            return []

        events = []
        try:
            with open(event_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = PersistedEvent.from_json_line(line)
                        if event.sequence > since_sequence:
                            events.append(event)
                    except Exception as e:
                        logger.warning(f"Failed to parse event line: {e}")
        except Exception as e:
            logger.error(f"Failed to load events from {event_file}: {e}")

        return events

    def get_latest_sequence(self, session_name: str) -> int:
        """Get the latest sequence number for a session."""
        event_file = self._get_event_file(session_name)
        if not event_file.exists():
            return 0

        latest = 0
        try:
            # Read last line efficiently
            with open(event_file, "rb") as f:
                # Seek to end
                f.seek(0, 2)
                file_size = f.tell()
                if file_size == 0:
                    return 0

                # Read last chunk to find last line
                chunk_size = min(4096, file_size)
                f.seek(-chunk_size, 2)
                last_chunk = f.read().decode("utf-8")
                lines = last_chunk.strip().split("\n")
                if lines:
                    last_line = lines[-1]
                    event = PersistedEvent.from_json_line(last_line)
                    latest = event.sequence
        except Exception as e:
            logger.warning(f"Failed to get latest sequence: {e}")

        return latest

    def get_oldest_sequence(self, session_name: str) -> int:
        """Get the oldest sequence number for a session."""
        event_file = self._get_event_file(session_name)
        if not event_file.exists():
            return 0

        try:
            with open(event_file) as f:
                first_line = f.readline().strip()
                if first_line:
                    event = PersistedEvent.from_json_line(first_line)
                    return event.sequence
        except Exception as e:
            logger.warning(f"Failed to get oldest sequence: {e}")

        return 0

    def clear_events(self, session_name: str) -> None:
        """Remove all events for a session."""
        event_file = self._get_event_file(session_name)
        if event_file.exists():
            event_file.unlink()

    def clear_all(self) -> None:
        """Remove all event files."""
        if self.base_dir.exists():
            for event_file in self.base_dir.glob("*.jsonl"):
                event_file.unlink()

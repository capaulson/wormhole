"""WebSocket protocol message types."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# === Phone → Daemon ===


class HelloMessage(BaseModel):
    type: Literal["hello"] = "hello"
    client_version: str
    device_name: str


class SubscribeMessage(BaseModel):
    type: Literal["subscribe"] = "subscribe"
    sessions: list[str] | Literal["*"]


class InputMessage(BaseModel):
    type: Literal["input"] = "input"
    session: str
    text: str


class PermissionResponseMessage(BaseModel):
    type: Literal["permission_response"] = "permission_response"
    request_id: str
    decision: Literal["allow", "deny"]


class ControlMessage(BaseModel):
    type: Literal["control"] = "control"
    session: str
    action: Literal["interrupt", "compact", "clear", "plan"]


class SyncMessage(BaseModel):
    type: Literal["sync"] = "sync"
    session: str
    last_seen_sequence: int


ClientMessage = (
    HelloMessage
    | SubscribeMessage
    | InputMessage
    | PermissionResponseMessage
    | ControlMessage
    | SyncMessage
)


def parse_client_message(raw: str) -> ClientMessage:
    """Parse incoming WebSocket message from phone."""
    data = json.loads(raw)
    msg_type = data.get("type")

    match msg_type:
        case "hello":
            return HelloMessage.model_validate(data)
        case "subscribe":
            return SubscribeMessage.model_validate(data)
        case "input":
            return InputMessage.model_validate(data)
        case "permission_response":
            return PermissionResponseMessage.model_validate(data)
        case "control":
            return ControlMessage.model_validate(data)
        case "sync":
            return SyncMessage.model_validate(data)
        case _:
            raise ValueError(f"Unknown message type: {msg_type}")


# === Daemon → Phone ===


class PendingPermissionInfo(BaseModel):
    """Pending permission request info for reconnection recovery."""
    request_id: str
    tool_name: str
    tool_input: dict[str, Any]
    session_name: str
    created_at: datetime


class SessionInfo(BaseModel):
    name: str
    directory: str
    state: str
    claude_session_id: str | None = None
    cost_usd: float = 0.0
    last_activity: datetime | None = None
    pending_permissions: list[PendingPermissionInfo] = []


class WelcomeMessage(BaseModel):
    type: Literal["welcome"] = "welcome"
    server_version: str
    machine_name: str
    sessions: list[SessionInfo]


class EventMessage(BaseModel):
    type: Literal["event"] = "event"
    session: str
    sequence: int
    timestamp: datetime
    message: dict[str, Any]


class PermissionRequestMessage(BaseModel):
    type: Literal["permission_request"] = "permission_request"
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str
    tool_input: dict[str, Any]
    session_name: str


class SyncResponseMessage(BaseModel):
    type: Literal["sync_response"] = "sync_response"
    session: str
    events: list[EventMessage]
    pending_permissions: list[PendingPermissionInfo] = []
    oldest_available_sequence: int = 0  # Oldest sequence still in buffer


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    session: str | None = None
    details: dict[str, Any] | None = None


ServerMessage = (
    WelcomeMessage
    | EventMessage
    | PermissionRequestMessage
    | SyncResponseMessage
    | ErrorMessage
)

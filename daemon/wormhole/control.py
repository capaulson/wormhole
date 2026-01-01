"""Control socket for CLI-daemon IPC."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


def get_socket_path() -> Path:
    """Get the path to the control socket."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return Path(runtime_dir) / "wormhole.sock"


# === Control Messages ===


class OpenSessionRequest(BaseModel):
    type: Literal["open_session"] = "open_session"
    name: str
    directory: str
    options: dict[str, Any] | None = None


class CloseSessionRequest(BaseModel):
    type: Literal["close_session"] = "close_session"
    name: str


class ListSessionsRequest(BaseModel):
    type: Literal["list_sessions"] = "list_sessions"


class GetStatusRequest(BaseModel):
    type: Literal["get_status"] = "get_status"


class QuerySessionRequest(BaseModel):
    type: Literal["query_session"] = "query_session"
    name: str
    text: str


ControlRequest = (
    OpenSessionRequest
    | CloseSessionRequest
    | ListSessionsRequest
    | GetStatusRequest
    | QuerySessionRequest
)


class SessionInfoResponse(BaseModel):
    name: str
    directory: str
    state: str
    claude_session_id: str | None = None
    cost_usd: float = 0.0


class SuccessResponse(BaseModel):
    type: Literal["success"] = "success"
    message: str = ""
    data: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class SessionListResponse(BaseModel):
    type: Literal["session_list"] = "session_list"
    sessions: list[SessionInfoResponse]


class StatusResponse(BaseModel):
    type: Literal["status"] = "status"
    running: bool = True
    port: int
    machine_name: str
    session_count: int
    connected_clients: int


ControlResponse = SuccessResponse | ErrorResponse | SessionListResponse | StatusResponse


def parse_control_request(raw: str) -> ControlRequest:
    """Parse incoming control request."""
    data = json.loads(raw)
    msg_type = data.get("type")

    match msg_type:
        case "open_session":
            return OpenSessionRequest.model_validate(data)
        case "close_session":
            return CloseSessionRequest.model_validate(data)
        case "list_sessions":
            return ListSessionsRequest.model_validate(data)
        case "get_status":
            return GetStatusRequest.model_validate(data)
        case "query_session":
            return QuerySessionRequest.model_validate(data)
        case _:
            raise ValueError(f"Unknown control message type: {msg_type}")


# === Client Functions ===


async def send_control_request(request: ControlRequest) -> ControlResponse:
    """Send a control request to the daemon and get response."""
    socket_path = get_socket_path()

    if not socket_path.exists():
        return ErrorResponse(
            code="DAEMON_NOT_RUNNING",
            message="Wormhole daemon is not running. Start it with: wormhole daemon",
        )

    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))

        # Send request
        request_data = request.model_dump_json() + "\n"
        writer.write(request_data.encode())
        await writer.drain()

        # Read response
        response_data = await reader.readline()
        writer.close()
        await writer.wait_closed()

        # Parse response
        response_dict = json.loads(response_data.decode())
        response_type = response_dict.get("type")

        match response_type:
            case "success":
                return SuccessResponse.model_validate(response_dict)
            case "error":
                return ErrorResponse.model_validate(response_dict)
            case "session_list":
                return SessionListResponse.model_validate(response_dict)
            case "status":
                return StatusResponse.model_validate(response_dict)
            case _:
                return ErrorResponse(
                    code="INVALID_RESPONSE",
                    message=f"Unknown response type: {response_type}",
                )

    except ConnectionRefusedError:
        return ErrorResponse(
            code="DAEMON_NOT_RUNNING",
            message="Wormhole daemon is not running. Start it with: wormhole daemon",
        )
    except Exception as e:
        return ErrorResponse(
            code="CONNECTION_ERROR",
            message=f"Failed to connect to daemon: {e}",
        )


def send_control_request_sync(request: ControlRequest) -> ControlResponse:
    """Synchronous wrapper for send_control_request."""
    return asyncio.run(send_control_request(request))

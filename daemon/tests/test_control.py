"""Tests for control socket IPC."""

import json

import pytest

from wormhole.control import (
    CloseSessionRequest,
    ErrorResponse,
    GetStatusRequest,
    ListSessionsRequest,
    OpenSessionRequest,
    QuerySessionRequest,
    SessionListResponse,
    StatusResponse,
    SuccessResponse,
    parse_control_request,
)


class TestControlRequestParsing:
    """Tests for parsing control requests."""

    def test_parse_open_session(self) -> None:
        raw = json.dumps({
            "type": "open_session",
            "name": "test-session",
            "directory": "/home/user/project",
        })
        request = parse_control_request(raw)
        assert isinstance(request, OpenSessionRequest)
        assert request.name == "test-session"
        assert request.directory == "/home/user/project"

    def test_parse_open_session_with_options(self) -> None:
        raw = json.dumps({
            "type": "open_session",
            "name": "test",
            "directory": "/tmp",
            "options": {"model": "claude-sonnet-4-5"},
        })
        request = parse_control_request(raw)
        assert isinstance(request, OpenSessionRequest)
        assert request.options == {"model": "claude-sonnet-4-5"}

    def test_parse_close_session(self) -> None:
        raw = json.dumps({
            "type": "close_session",
            "name": "test-session",
        })
        request = parse_control_request(raw)
        assert isinstance(request, CloseSessionRequest)
        assert request.name == "test-session"

    def test_parse_list_sessions(self) -> None:
        raw = json.dumps({"type": "list_sessions"})
        request = parse_control_request(raw)
        assert isinstance(request, ListSessionsRequest)

    def test_parse_get_status(self) -> None:
        raw = json.dumps({"type": "get_status"})
        request = parse_control_request(raw)
        assert isinstance(request, GetStatusRequest)

    def test_parse_query_session(self) -> None:
        raw = json.dumps({
            "type": "query_session",
            "name": "test",
            "text": "Hello Claude",
        })
        request = parse_control_request(raw)
        assert isinstance(request, QuerySessionRequest)
        assert request.name == "test"
        assert request.text == "Hello Claude"

    def test_parse_unknown_type_raises(self) -> None:
        raw = json.dumps({"type": "unknown"})
        with pytest.raises(ValueError, match="Unknown control message type"):
            parse_control_request(raw)


class TestControlResponseSerialization:
    """Tests for response serialization."""

    def test_success_response(self) -> None:
        response = SuccessResponse(message="Session created")
        data = json.loads(response.model_dump_json())
        assert data["type"] == "success"
        assert data["message"] == "Session created"

    def test_success_response_with_data(self) -> None:
        response = SuccessResponse(
            message="OK",
            data={"session_id": "abc123"},
        )
        data = json.loads(response.model_dump_json())
        assert data["data"]["session_id"] == "abc123"

    def test_error_response(self) -> None:
        response = ErrorResponse(
            code="SESSION_EXISTS",
            message="A session already exists in this directory",
        )
        data = json.loads(response.model_dump_json())
        assert data["type"] == "error"
        assert data["code"] == "SESSION_EXISTS"

    def test_session_list_response(self) -> None:
        response = SessionListResponse(sessions=[])
        data = json.loads(response.model_dump_json())
        assert data["type"] == "session_list"
        assert data["sessions"] == []

    def test_status_response(self) -> None:
        response = StatusResponse(
            running=True,
            port=7117,
            machine_name="testbox",
            session_count=2,
            connected_clients=1,
        )
        data = json.loads(response.model_dump_json())
        assert data["type"] == "status"
        assert data["port"] == 7117
        assert data["session_count"] == 2

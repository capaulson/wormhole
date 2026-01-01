"""Tests for protocol message parsing."""

import json

import pytest

from wormhole.protocol import (
    HelloMessage,
    InputMessage,
    PermissionResponseMessage,
    parse_client_message,
)


class TestClientMessageParsing:
    """Tests for parsing messages from phone."""

    def test_parse_hello(self) -> None:
        raw = json.dumps({
            "type": "hello",
            "client_version": "1.0.0",
            "device_name": "Test iPhone",
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, HelloMessage)
        assert msg.client_version == "1.0.0"
        assert msg.device_name == "Test iPhone"

    def test_parse_input(self) -> None:
        raw = json.dumps({
            "type": "input",
            "session": "test-session",
            "text": "Hello Claude",
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, InputMessage)
        assert msg.session == "test-session"
        assert msg.text == "Hello Claude"

    def test_parse_permission_response_allow(self) -> None:
        raw = json.dumps({
            "type": "permission_response",
            "request_id": "abc123",
            "decision": "allow",
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, PermissionResponseMessage)
        assert msg.request_id == "abc123"
        assert msg.decision == "allow"

    def test_parse_permission_response_deny(self) -> None:
        raw = json.dumps({
            "type": "permission_response",
            "request_id": "abc123",
            "decision": "deny",
        })
        msg = parse_client_message(raw)
        assert isinstance(msg, PermissionResponseMessage)
        assert msg.decision == "deny"

    def test_parse_unknown_type_raises(self) -> None:
        raw = json.dumps({"type": "unknown"})
        with pytest.raises(ValueError, match="Unknown message type"):
            parse_client_message(raw)

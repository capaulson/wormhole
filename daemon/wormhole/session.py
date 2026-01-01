"""Claude Code session wrapper."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeSDKClient, ToolPermissionContext

from wormhole.protocol import EventMessage, PermissionRequestMessage


class SessionState(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    AWAITING_APPROVAL = "awaiting_approval"
    ERROR = "error"


class BufferedEvent(BaseModel):
    sequence: int
    timestamp: datetime
    message: dict[str, Any]


class WormholeSession:
    """Wraps a ClaudeSDKClient with permission routing and event buffering."""

    def __init__(
        self,
        name: str,
        directory: Path,
        buffer_size: int = 1000,
    ) -> None:
        self.name = name
        self.directory = directory
        self.buffer_size = buffer_size

        self.state = SessionState.IDLE
        self.claude_session_id: str | None = None
        self.cost_usd: float = 0.0
        self.last_activity: datetime | None = None

        self._client: ClaudeSDKClient | None = None
        self._event_buffer: deque[BufferedEvent] = deque(maxlen=buffer_size)
        self._sequence: int = 0
        self._pending_permissions: dict[str, asyncio.Future[str]] = {}

        # Callback to broadcast events to WebSocket clients
        self._broadcast_callback: Any = None

    def set_broadcast_callback(self, callback: Any) -> None:
        """Set callback for broadcasting events to connected clients."""
        self._broadcast_callback = callback

    async def start(self, options: dict[str, Any] | None = None) -> None:
        """Start the Claude SDK client."""
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        sdk_options = ClaudeAgentOptions(
            cwd=str(self.directory),
            can_use_tool=self._permission_handler,
            permission_mode="default",
            **(options or {}),
        )

        self._client = ClaudeSDKClient(sdk_options)
        await self._client.connect()

    async def stop(self) -> None:
        """Stop the Claude SDK client."""
        if self._client:
            await self._client.disconnect()
            self._client = None
        self.state = SessionState.IDLE

    async def query(self, text: str) -> None:
        """Send a query to Claude."""
        if not self._client:
            raise RuntimeError("Session not started")

        self.state = SessionState.WORKING
        self.last_activity = datetime.now()

        await self._client.query(text)

        # Start receiving responses in background
        asyncio.create_task(self._receive_responses())

    async def interrupt(self) -> None:
        """Interrupt current operation."""
        if self._client:
            await self._client.interrupt()

    def respond_to_permission(self, request_id: str, decision: str) -> bool:
        """Respond to a pending permission request."""
        future = self._pending_permissions.get(request_id)
        if future and not future.done():
            future.set_result(decision)
            return True
        return False

    def get_events_since(self, sequence: int) -> list[BufferedEvent]:
        """Get buffered events since given sequence number."""
        return [e for e in self._event_buffer if e.sequence > sequence]

    async def _permission_handler(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> Any:  # Returns PermissionResultAllow | PermissionResultDeny
        """Handle permission request from SDK."""
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        self.state = SessionState.AWAITING_APPROVAL
        request_id = str(uuid.uuid4())

        # Create future for response
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending_permissions[request_id] = future

        # Broadcast permission request
        if self._broadcast_callback:
            msg = PermissionRequestMessage(
                request_id=request_id,
                tool_name=tool_name,
                tool_input=input_data,
                session_name=self.name,
            )
            await self._broadcast_callback(msg)

        # Wait for response (no timeout in V1)
        try:
            decision = await future
        finally:
            self._pending_permissions.pop(request_id, None)
            self.state = SessionState.WORKING

        if decision == "allow":
            return PermissionResultAllow(updated_input=input_data)
        else:
            return PermissionResultDeny(message="User denied", interrupt=False)

    async def _receive_responses(self) -> None:
        """Receive and process responses from Claude."""
        if not self._client:
            return

        try:
            async for message in self._client.receive_response():
                await self._handle_sdk_message(message)
        except Exception:
            self.state = SessionState.ERROR
            # TODO: Broadcast error
            raise

        self.state = SessionState.IDLE

    async def _handle_sdk_message(self, message: Any) -> None:
        """Process a message from the SDK."""
        from dataclasses import asdict, is_dataclass

        self._sequence += 1
        now = datetime.now()
        self.last_activity = now

        # Convert SDK message to dict[str, Any]
        msg_dict: dict[str, Any]
        if isinstance(message, dict):
            msg_dict = message
        elif is_dataclass(message) and not isinstance(message, type):
            msg_dict = asdict(message)
        else:
            # Try model_dump for Pydantic models, fall back to string representation
            dump_fn = getattr(message, "model_dump", None)
            if callable(dump_fn):
                result = dump_fn()
                msg_dict = result if isinstance(result, dict) else {"raw": str(result)}
            else:
                msg_dict = {"raw": str(message)}

        # Buffer event
        event = BufferedEvent(
            sequence=self._sequence,
            timestamp=now,
            message=msg_dict,
        )
        self._event_buffer.append(event)

        # Capture session ID from init message
        # SDK SystemMessage has: subtype, data where data contains session_id
        if msg_dict.get("subtype") == "init":
            data = msg_dict.get("data", {})
            if isinstance(data, dict) and "session_id" in data:
                self.claude_session_id = str(data["session_id"])

        # Update cost from result message (ResultMessage has total_cost_usd directly)
        cost = msg_dict.get("total_cost_usd")
        if cost is not None and isinstance(cost, (int, float)):
            self.cost_usd = float(cost)

        # Broadcast to connected clients
        if self._broadcast_callback:
            broadcast_msg = EventMessage(
                session=self.name,
                sequence=self._sequence,
                timestamp=now,
                message=msg_dict,
            )
            await self._broadcast_callback(broadcast_msg)

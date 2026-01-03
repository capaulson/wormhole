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

from wormhole.persistence import EventPersistence, PersistedEvent
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

    def estimated_size(self) -> int:
        """Estimate the size of this event in bytes."""
        import json
        # Rough estimate: JSON serialized size + overhead
        return len(json.dumps(self.message)) + 100


class PendingPermission(BaseModel):
    """Stored pending permission request for reconnection recovery."""
    request_id: str
    tool_name: str
    tool_input: dict[str, Any]
    created_at: datetime


# Default 2MB buffer size
DEFAULT_BUFFER_SIZE_BYTES = 2 * 1024 * 1024


class WormholeSession:
    """Wraps a ClaudeSDKClient with permission routing and event buffering."""

    def __init__(
        self,
        name: str,
        directory: Path,
        buffer_size_bytes: int = DEFAULT_BUFFER_SIZE_BYTES,
        event_persistence: EventPersistence | None = None,
    ) -> None:
        self.name = name
        self.directory = directory
        self.buffer_size_bytes = buffer_size_bytes

        self.state = SessionState.IDLE
        self.claude_session_id: str | None = None
        self.cost_usd: float = 0.0
        self.last_activity: datetime | None = None

        self._client: ClaudeSDKClient | None = None
        self._event_buffer: deque[BufferedEvent] = deque()
        self._event_buffer_size: int = 0  # Current buffer size in bytes
        self._sequence: int = 0
        self._pending_permissions: dict[str, asyncio.Future[str]] = {}
        self._pending_permission_details: dict[str, PendingPermission] = {}

        # Event persistence for full history
        self._event_persistence = event_persistence or EventPersistence()
        # Restore sequence from persisted events
        self._sequence = self._event_persistence.get_latest_sequence(name)

        # Callback to broadcast events to WebSocket clients
        self._broadcast_callback: Any = None
        # Callback to persist session state changes
        self._persistence_callback: Any = None

        # Store original options for restart
        self._startup_options: dict[str, Any] = {}

    def set_broadcast_callback(self, callback: Any) -> None:
        """Set callback for broadcasting events to connected clients."""
        self._broadcast_callback = callback

    def set_persistence_callback(self, callback: Any) -> None:
        """Set callback for persisting session state changes."""
        self._persistence_callback = callback

    async def start(self, options: dict[str, Any] | None = None) -> None:
        """Start the Claude SDK client."""
        import logging
        import shutil

        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        logger = logging.getLogger(__name__)
        options = dict(options) if options else {}  # Make a copy

        # Store original options for restart (only on first call)
        if not self._startup_options:
            self._startup_options = dict(options)

        # Use system claude CLI if available (for Max plan support)
        cli_path = shutil.which("claude")
        logger.info(f"Using Claude CLI: {cli_path or 'bundled'}")

        # Override ANTHROPIC_API_KEY to empty string so Claude uses Max plan
        logger.info("Overriding ANTHROPIC_API_KEY to use Max plan with model=opus")

        # Map CLI flags to SDK options
        # SDK permission_mode: 'default', 'acceptEdits', 'plan', 'bypassPermissions'
        permission_mode: str | None = None
        if options.pop("dangerously_skip_permissions", None) is not None:
            permission_mode = "bypassPermissions"
            logger.warning("Running with bypassPermissions mode")
        elif options.pop("accept_edits", None) is not None:
            permission_mode = "acceptEdits"
        elif options.pop("plan", None) is not None:
            permission_mode = "plan"

        # Enable continue_conversation by default for multi-turn conversations
        if "continue_conversation" not in options:
            options["continue_conversation"] = True

        # SDK boolean options - convert None to True
        sdk_bool_options = [
            "continue_conversation", "include_partial_messages",
            "fork_session", "enable_file_checkpointing",
        ]
        for opt in sdk_bool_options:
            if opt in options and options[opt] is None:
                options[opt] = True

        # Extract known SDK options
        sdk_opts: dict[str, Any] = {
            "cwd": str(self.directory),
            "cli_path": cli_path,
            "env": {"ANTHROPIC_API_KEY": ""},  # Override API key to force Max plan
            "model": options.pop("model", "opus"),
            # CRITICAL: Use preset system prompt to preserve Claude Code's default prompt
            # If system_prompt is None, SDK passes --system-prompt "" which REPLACES
            # the default prompt, removing all tool awareness. Using
            # {"type": "preset", "append": ""} preserves the default prompt.
            "system_prompt": options.pop("system_prompt", {"type": "preset", "append": ""}),
        }

        # Add permission handling
        if permission_mode:
            sdk_opts["permission_mode"] = permission_mode
        else:
            sdk_opts["can_use_tool"] = self._permission_handler

        # Map known options to SDK parameters
        known_sdk_opts = [
            "max_turns", "max_budget_usd", "resume",
            "continue_conversation", "include_partial_messages",
            "fork_session", "enable_file_checkpointing", "max_thinking_tokens",
            "tools", "allowed_tools", "disallowed_tools", "fallback_model",
        ]
        for opt in known_sdk_opts:
            if opt in options:
                sdk_opts[opt] = options.pop(opt)

        # Any remaining options go to extra_args (passed to CLI)
        if options:
            # Convert back to CLI format (underscores to dashes)
            extra_args = {}
            for key, value in options.items():
                cli_key = key.replace("_", "-")
                extra_args[cli_key] = value if value is not None else ""
            sdk_opts["extra_args"] = extra_args
            logger.debug(f"Passing extra_args to CLI: {extra_args}")

        sdk_options = ClaudeAgentOptions(**sdk_opts)

        self._client = ClaudeSDKClient(sdk_options)
        await self._client.connect()

    async def stop(self) -> None:
        """Stop the Claude SDK client."""
        if self._client:
            try:
                await self._client.disconnect()
            except AttributeError as e:
                # Handle SDK internal errors (e.g., TaskGroup._exceptions missing)
                import logging
                logging.getLogger(__name__).debug(f"SDK disconnect error (ignored): {e}")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error disconnecting SDK client: {e}")
            self._client = None
        self.state = SessionState.IDLE

    async def query(self, text: str) -> None:
        """Send a query to Claude."""
        # Auto-restart if session died
        if self.state == SessionState.ERROR or not self._client:
            await self._restart()

        self.state = SessionState.WORKING
        self.last_activity = datetime.now()

        try:
            await self._client.query(text)
            # Start receiving responses in background
            asyncio.create_task(self._receive_responses())
        except Exception:
            # If query fails, try to restart and retry once
            self.state = SessionState.ERROR
            await self._restart()
            self.state = SessionState.WORKING
            await self._client.query(text)
            asyncio.create_task(self._receive_responses())

    async def _restart(self) -> None:
        """Restart the Claude SDK client, resuming the existing Claude session if possible."""
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Restarting session {self.name}")

        # Disconnect old client if any
        if self._client:
            try:  # noqa: SIM105 - async code can't use contextlib.suppress
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

        # Prepare restart options from stored originals
        restart_options = dict(self._startup_options)

        # CRITICAL: Resume the existing Claude session if we have a session ID
        # This ensures conversation context (tools, codebase knowledge) is preserved
        if self.claude_session_id:
            restart_options["resume"] = self.claude_session_id
            logger.info(f"Resuming Claude session: {self.claude_session_id}")

        await self.start(restart_options)
        self.state = SessionState.IDLE

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
        """Get events since given sequence number.

        First checks in-memory buffer, then falls back to persisted events.
        """
        # Check in-memory buffer first
        buffered = [e for e in self._event_buffer if e.sequence > sequence]
        # If we have buffered events and the first one is what they need, use buffer
        if buffered and buffered[0].sequence == sequence + 1:
            return buffered

        # Fall back to persisted events
        persisted = self._event_persistence.load_events(self.name, since_sequence=sequence)
        return [
            BufferedEvent(
                sequence=e.sequence,
                timestamp=e.timestamp,
                message=e.message,
            )
            for e in persisted
        ]

    def get_oldest_sequence(self) -> int:
        """Get the oldest sequence number available (from persistence)."""
        return self._event_persistence.get_oldest_sequence(self.name)

    def get_pending_permissions(self) -> list[PendingPermission]:
        """Get all pending permission requests (for reconnection recovery)."""
        return list(self._pending_permission_details.values())

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

        # Store permission details for reconnection recovery
        self._pending_permission_details[request_id] = PendingPermission(
            request_id=request_id,
            tool_name=tool_name,
            tool_input=input_data,
            created_at=datetime.now(),
        )

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
            self._pending_permission_details.pop(request_id, None)
            self.state = SessionState.WORKING

        if decision == "allow":
            return PermissionResultAllow(updated_input=input_data)
        else:
            return PermissionResultDeny(message="User denied", interrupt=False)

    async def _receive_responses(self) -> None:
        """Receive and process responses from Claude."""
        import logging

        logger = logging.getLogger(__name__)

        if not self._client:
            return

        try:
            async for message in self._client.receive_response():
                await self._handle_sdk_message(message)
        except Exception as e:
            logger.error(f"Error receiving responses in session {self.name}: {e}")
            self.state = SessionState.ERROR

            # Broadcast error event
            if self._broadcast_callback:
                from wormhole.protocol import ErrorMessage
                error_msg = ErrorMessage(
                    code="SDK_ERROR",
                    message=f"Session error: {str(e)}",
                    session=self.name,
                )
                try:  # noqa: SIM105 - async code can't use contextlib.suppress
                    await self._broadcast_callback(error_msg)
                except Exception:
                    pass
            return  # Don't raise, just return so session can be restarted

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

        # Buffer event with size-based eviction
        event = BufferedEvent(
            sequence=self._sequence,
            timestamp=now,
            message=msg_dict,
        )
        event_size = event.estimated_size()
        self._event_buffer.append(event)
        self._event_buffer_size += event_size

        # Persist event to disk for full history
        self._event_persistence.append_event(
            self.name,
            PersistedEvent(
                sequence=self._sequence,
                timestamp=now,
                message=msg_dict,
            ),
        )

        # Evict old events from memory buffer if exceeds size limit
        # (persisted events are kept on disk)
        while self._event_buffer_size > self.buffer_size_bytes and self._event_buffer:
            old_event = self._event_buffer.popleft()
            self._event_buffer_size -= old_event.estimated_size()

        # Capture session ID from init message
        # SDK SystemMessage has: subtype, data where data contains session_id
        if msg_dict.get("subtype") == "init":
            data = msg_dict.get("data", {})
            if isinstance(data, dict) and "session_id" in data:
                self.claude_session_id = str(data["session_id"])
                # Persist session ID capture
                if self._persistence_callback:
                    self._persistence_callback(self)

        # Update cost from result message (ResultMessage has total_cost_usd directly)
        cost = msg_dict.get("total_cost_usd")
        if cost is not None and isinstance(cost, (int, float)):
            self.cost_usd = float(cost)
            # Persist cost update
            if self._persistence_callback:
                self._persistence_callback(self)

        # Broadcast to connected clients
        if self._broadcast_callback:
            broadcast_msg = EventMessage(
                session=self.name,
                sequence=self._sequence,
                timestamp=now,
                message=msg_dict,
            )
            await self._broadcast_callback(broadcast_msg)

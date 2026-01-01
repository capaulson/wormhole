# CLAUDE.md — Wormhole Project Instructions

## Project Overview

Wormhole is a remote Claude Code session manager. It consists of:
1. **Python daemon** — Runs on dev machines, wraps Claude Agent SDK
2. **iOS app** — SwiftUI app for iPhone to monitor/control sessions

See `docs/PRD.md` for full requirements.

## Architecture Decisions (Do Not Deviate)

- Use `claude-agent-sdk` Python package directly (NOT CLI spawning)
- Use `can_use_tool` callback for permission routing (NOT hooks)
- One session per directory (enforce in daemon)
- WebSocket for phone↔daemon communication
- mDNS/Bonjour for discovery
- No authentication in V1 (network trust)

## Code Style

### Python (daemon/)
- Python 3.11+
- Use `uv` for package management
- Type hints on all functions
- Async/await for all I/O
- Pydantic v2 for models (not dataclasses)
- `ruff` for linting (default rules)
- `pyright` for type checking (strict mode)
- Tests with `pytest` + `pytest-asyncio`

### Swift (ios/)
- iOS 17+ deployment target
- SwiftUI only (no UIKit)
- Swift 5.9+
- Use Swift Testing framework (not XCTest for new tests)
- Async/await for networking
- Observable macro for view models

## File Structure (Create Exactly This)

```
wormhole/
├── CLAUDE.md                    # This file
├── README.md                    # User-facing docs
├── docs/
│   └── PRD.md                   # Product requirements
│
├── daemon/
│   ├── pyproject.toml           # Use template below
│   ├── uv.lock                  # Generated
│   ├── wormhole/
│   │   ├── __init__.py          # Version only
│   │   ├── __main__.py          # CLI entry: `python -m wormhole`
│   │   ├── cli.py               # Click commands
│   │   ├── daemon.py            # WormholeDaemon class
│   │   ├── session.py           # WormholeSession class
│   │   ├── permissions.py       # Permission routing
│   │   ├── websocket.py         # WebSocket server
│   │   ├── discovery.py         # mDNS advertisement
│   │   ├── protocol.py          # Pydantic message models
│   │   └── config.py            # Configuration loading
│   │
│   └── tests/
│       ├── conftest.py          # Fixtures
│       ├── fixtures/            # Sample JSON messages
│       │   ├── system_init.json
│       │   ├── assistant_message.json
│       │   ├── permission_request.json
│       │   └── result.json
│       ├── test_session.py
│       ├── test_permissions.py
│       ├── test_websocket.py
│       ├── test_protocol.py
│       ├── test_cli.py
│       └── test_sdk_compat.py
│
└── ios/
    ├── Wormhole.xcodeproj
    └── Wormhole/
        ├── WormholeApp.swift
        ├── ContentView.swift
        ├── Models/
        ├── Views/
        ├── Services/
        └── Resources/
```

## Key Implementation Patterns

### Permission Callback (CRITICAL)

```python
# This is the core of the system. Get this right.
async def permission_handler(
    tool_name: str,
    input_data: dict[str, Any],
    context: dict[str, Any]
) -> dict[str, Any]:
    """Route permission request to phone, await response."""
    request_id = str(uuid.uuid4())
    
    # Create pending request
    future: asyncio.Future[str] = asyncio.Future()
    self.pending_permissions[request_id] = future
    
    # Send to all connected phones
    await self.broadcast(PermissionRequest(
        request_id=request_id,
        tool_name=tool_name,
        tool_input=input_data,
        session_name=self.name
    ))
    
    # Block until phone responds (no timeout in V1)
    decision = await future
    
    # Clean up
    del self.pending_permissions[request_id]
    
    if decision == "allow":
        return {"behavior": "allow", "updated_input": input_data}
    else:
        return {"behavior": "deny", "message": "User denied", "interrupt": False}
```

### WebSocket Message Handling

```python
async def handle_message(self, ws: WebSocket, raw: str) -> None:
    """Dispatch incoming WebSocket messages."""
    msg = parse_client_message(raw)  # Returns union type
    
    match msg:
        case HelloMessage():
            await self.handle_hello(ws, msg)
        case SubscribeMessage():
            await self.handle_subscribe(ws, msg)
        case InputMessage():
            await self.handle_input(msg)
        case PermissionResponseMessage():
            await self.handle_permission_response(msg)
        case ControlMessage():
            await self.handle_control(msg)
        case SyncMessage():
            await self.handle_sync(ws, msg)
```

### Session State Machine

```python
class SessionState(Enum):
    IDLE = "idle"
    WORKING = "working"
    AWAITING_APPROVAL = "awaiting_approval"
    ERROR = "error"

# State transitions (enforce these)
# IDLE -> WORKING (on query)
# WORKING -> AWAITING_APPROVAL (on can_use_tool called)
# AWAITING_APPROVAL -> WORKING (on permission response)
# WORKING -> IDLE (on result)
# ANY -> ERROR (on error)
```

## Templates

### pyproject.toml

```toml
[project]
name = "wormhole"
version = "0.1.0"
description = "Remote Claude Code session manager"
requires-python = ">=3.11"
dependencies = [
    "claude-agent-sdk>=0.1.23,<0.2.0",
    "websockets>=12.0,<13.0",
    "zeroconf>=0.131.0,<1.0.0",
    "click>=8.1.0,<9.0.0",
    "pydantic>=2.5.0,<3.0.0",
    "tomli>=2.0.0,<3.0.0; python_version < '3.11'",
]

[project.scripts]
wormhole = "wormhole.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.12.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
    "pyright>=1.1.350",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "strict"
```

### Protocol Models (protocol.py)

```python
"""WebSocket protocol message types."""
from __future__ import annotations
from typing import Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


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
    """Parse incoming WebSocket message."""
    import json
    data = json.loads(raw)
    msg_type = data.get("type")
    
    match msg_type:
        case "hello": return HelloMessage.model_validate(data)
        case "subscribe": return SubscribeMessage.model_validate(data)
        case "input": return InputMessage.model_validate(data)
        case "permission_response": return PermissionResponseMessage.model_validate(data)
        case "control": return ControlMessage.model_validate(data)
        case "sync": return SyncMessage.model_validate(data)
        case _: raise ValueError(f"Unknown message type: {msg_type}")


# === Daemon → Phone ===

class SessionInfo(BaseModel):
    name: str
    directory: str
    state: str
    claude_session_id: str | None = None
    cost_usd: float = 0.0
    last_activity: datetime


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
    message: dict[str, Any]  # SDK message, passed through


class PermissionRequest(BaseModel):
    type: Literal["permission_request"] = "permission_request"
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str
    tool_input: dict[str, Any]
    session_name: str


class SyncResponse(BaseModel):
    type: Literal["sync_response"] = "sync_response"
    session: str
    events: list[EventMessage]


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    session: str | None = None


ServerMessage = (
    WelcomeMessage 
    | EventMessage 
    | PermissionRequest 
    | SyncResponse 
    | ErrorMessage
)
```

## Test Fixtures

### fixtures/system_init.json
```json
{
  "type": "system",
  "subtype": "init",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "cwd": "/home/user/project",
  "tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
  "model": "claude-sonnet-4-5",
  "permission_mode": "default"
}
```

### fixtures/assistant_message.json
```json
{
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
          "content": "def authenticate(user, password):\n    pass\n"
        }
      }
    ]
  }
}
```

### fixtures/result.json
```json
{
  "type": "result",
  "subtype": "success",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_cost_usd": 0.0234,
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567
  }
}
```

## Acceptance Criteria (Per Phase)

### Phase 1: Core Session ✓
- [ ] `WormholeSession` wraps `ClaudeSDKClient`
- [ ] `can_use_tool` callback blocks until response received
- [ ] Permission allow/deny works correctly
- [ ] Events buffered with sequence numbers
- [ ] WebSocket server accepts connections
- [ ] Handshake (hello/welcome) works
- [ ] Events streamed to subscribed clients
- [ ] All unit tests pass
- [ ] Integration test with real SDK passes (simple prompt)

### Phase 2: CLI & Multi-Session ✓
- [ ] `wormhole daemon` starts daemon
- [ ] `wormhole open --name foo` creates session
- [ ] `wormhole open` in same dir fails with clear error
- [ ] `wormhole list` shows sessions with state
- [ ] `wormhole close foo` stops session
- [ ] `wormhole attach foo` spawns `claude --resume`
- [ ] `wormhole status` shows connection info
- [ ] Multiple concurrent sessions work
- [ ] All CLI options passed through to SDK

### Phase 3: Discovery & Sync ✓
- [ ] mDNS advertises `_wormhole._tcp.local`
- [ ] Service includes machine name and port
- [ ] Sync request returns events since sequence
- [ ] Config loaded from `~/.config/wormhole/config.toml`
- [ ] Environment variables override config
- [ ] Structured logging works

### Phase 4: iOS Core ✓
- [ ] App discovers machines via Bonjour
- [ ] Manual machine entry works
- [ ] WebSocket connects with handshake
- [ ] Session list shows all sessions
- [ ] State badges accurate (idle/working/awaiting)
- [ ] Reconnection with backoff works

### Phase 5: iOS Interaction ✓
- [ ] Event stream renders messages
- [ ] Permission card shows tool details
- [ ] Allow/Deny buttons work
- [ ] Quick actions (Stop, Plan, etc.) work
- [ ] Text input sends messages
- [ ] Voice dictation works
- [ ] Offline sync on reconnect works

### Phase 6: Polish ✓
- [ ] Error messages user-friendly
- [ ] Daemon restart doesn't lose sessions
- [ ] CI passes on Python 3.11, 3.12
- [ ] CI tests against pinned and latest SDK
- [ ] iOS builds and tests pass
- [ ] README complete
- [ ] TestFlight build uploaded

## Error Handling

### Error Codes (Use Consistently)

| Code | Description | User Message |
|------|-------------|--------------|
| `SESSION_EXISTS` | Session already exists in directory | "A session already exists in this directory: {name}" |
| `SESSION_NOT_FOUND` | Session name not found | "Session not found: {name}" |
| `SDK_ERROR` | Claude Agent SDK error | "Claude error: {details}" |
| `PERMISSION_TIMEOUT` | Permission request timed out | "Permission request timed out" |
| `WEBSOCKET_ERROR` | WebSocket connection error | "Connection error: {details}" |
| `INVALID_MESSAGE` | Malformed message | "Invalid message format" |
| `NOT_SUBSCRIBED` | Action on unsubscribed session | "Not subscribed to session: {name}" |

### Error Response Format

```python
class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str  # From table above
    message: str  # User-friendly message
    session: str | None = None  # If session-specific
    details: dict[str, Any] | None = None  # Debug info
```

## Common Mistakes to Avoid

1. **Don't use `asyncio.timeout()`** for permission requests in V1 — user explicitly wanted no timeout, just backup interrupt signal

2. **Don't create Screen sessions for SDK** — SDK runs in-process, only use Screen for `wormhole attach`

3. **Don't parse SDK output as JSON** — SDK gives us typed Python objects, use them directly

4. **Don't use hooks** — Use `can_use_tool` callback, not PreToolUse/PostToolUse hooks

5. **Don't forget to capture session_id** — It's in the first `system.init` message, save it for `wormhole attach`

6. **Don't use UIKit** — SwiftUI only for iOS

7. **Don't use XCTest for new tests** — Use Swift Testing framework

8. **Don't add authentication** — V1 relies on network trust

## Commands to Run

### Initial Setup
```bash
cd daemon
uv sync
uv run pytest  # Should pass (no tests yet is OK)
uv run ruff check .
uv run pyright
```

### Running Daemon
```bash
uv run wormhole daemon --port 7117
```

### Running Tests
```bash
uv run pytest                    # All tests
uv run pytest -m "not integration"  # Unit only
uv run pytest --cov               # With coverage
```

### iOS
```bash
cd ios
open Wormhole.xcodeproj
# Cmd+U to run tests
# Cmd+R to run app
```

## Questions? Don't Ask, Decide.

If you encounter ambiguity not covered here or in the PRD:
1. Pick the simpler option
2. Document your decision in a code comment
3. Add a test for the behavior you chose
4. Continue

Do not stop to ask clarifying questions. Make reasonable decisions and move forward.

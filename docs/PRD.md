# Wormhole: Remote Claude Code Session Manager

## Product Requirements Document
**Version:** 2.0  
**Date:** December 2025  
**Author:** Chris + Claude

---

## Executive Summary

Wormhole enables developers to monitor and interact with Claude Code sessions running on multiple machines from their iPhone. It solves the problem of being tethered to a desk while waiting for AI-assisted development tasks to complete—particularly valuable for parents and others who need to be mobile while working.

**Key Architecture Decision**: Wormhole uses the **Claude Agent SDK (Python)** directly, not CLI spawning with JSONL parsing. This gives us native `can_use_tool` callbacks for permission handling, built-in session management, and automatic context compaction.

---

## Problem Statement

Claude Code CLI is the most powerful way to interact with Claude for development work, but it requires sitting at a terminal. This creates friction for:

- **Parents** who can't sit at a computer for extended periods
- **Multi-machine workflows** where you're running sessions on laptops, desktops, and servers
- **Long-running tasks** where you want to step away but need to approve file changes or redirect Claude

Currently, there's no way to monitor or interact with Claude Code sessions remotely without VNC/SSH to a terminal, which is clunky on mobile.

---

## User Stories

1. **As a developer**, I want to start a Claude Code session on my server and monitor it from my phone so I can do other things while it works.

2. **As a parent**, I want to approve or reject Claude's proposed changes from my phone while supervising my kids.

3. **As someone with multiple machines**, I want a single interface to see all my active Claude Code sessions across my home network.

4. **As a remote worker**, I want to access my home development sessions over Tailscale while away from home.

5. **As a mobile user**, I want quick-action buttons for common operations since typing on a phone keyboard is cumbersome.

6. **As a power user**, I want to attach to my session from a real terminal when I'm back at my desk.

---

## Architecture

### Overview: SDK-Based Design

```
┌─────────────────────────────────────────────────────────────────┐
│   Machine A                                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    wormhole daemon                         │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │              Claude Agent SDK (Python)                │ │  │
│  │  │                                                       │ │  │
│  │  │  ┌─────────────┐    ┌─────────────┐                  │ │  │
│  │  │  │ Session 1   │    │ Session 2   │                  │ │  │
│  │  │  │ ~/project-a │    │ ~/project-b │                  │ │  │
│  │  │  │             │    │             │                  │ │  │
│  │  │  │ClaudeSDK    │    │ClaudeSDK    │                  │ │  │
│  │  │  │ Client      │    │ Client      │                  │ │  │
│  │  │  └──────┬──────┘    └──────┬──────┘                  │ │  │
│  │  │         │                  │                          │ │  │
│  │  │         │   can_use_tool callback                    │ │  │
│  │  │         │   (permission requests)                    │ │  │
│  │  │         │         │                                  │ │  │
│  │  │         └─────────┼──────────────────────────────────┤ │  │
│  │  │                   │                                  │ │  │
│  │  │  ┌────────────────▼────────────────────────────────┐ │ │  │
│  │  │  │         Permission Request Queue                │ │ │  │
│  │  │  │    (async: waits for phone response)            │ │ │  │
│  │  │  └─────────────────────────────────────────────────┘ │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  │                          │                                │  │
│  │              ┌───────────┴───────────┐                   │  │
│  │              │   WebSocket Server    │◄── mDNS advertise │  │
│  │              │   (stream events,     │                   │  │
│  │              │    receive responses) │                   │  │
│  │              └───────────────────────┘                   │  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │  Parallel Interactive Sessions (optional attach)    │ │  │
│  │  │                                                      │ │  │
│  │  │  screen -S wormhole-project-a                       │ │  │
│  │  │    └── claude --resume <session_id>                 │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                                 │
                    Local Network / Tailscale
                                 │
                        ┌────────┴────────┐
                        │    iPhone App   │
                        │    (Wormhole)   │
                        └─────────────────┘
```

### Design Principles

1. **SDK-Native**: Use Claude Agent SDK directly—not CLI spawning with output parsing.
2. **Distributed**: Each machine runs its own daemon. No central server required.
3. **Async Permissions**: `can_use_tool` callback awaits phone response before proceeding.
4. **One Session Per Directory**: Prevents conflicts and simplifies state management.
5. **Attachable**: Users can `wormhole attach` to spawn a parallel interactive CLI session.
6. **Simple**: Skip auth for V1—rely on network-level trust (local network / Tailscale).
7. **Passthrough**: Accept all standard Claude Code CLI options and defaults.

---

## Key Technical Discoveries

### Claude Agent SDK (Python)

The `claude-agent-sdk` Python package provides everything we need:

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

async def permission_handler(tool_name: str, input_data: dict, context: dict):
    """Called when Claude wants to use a tool requiring approval."""
    # Send to phone via WebSocket, await response
    response = await send_to_phone_and_wait(tool_name, input_data)
    
    if response == "allow":
        return {"behavior": "allow", "updated_input": input_data}
    else:
        return {"behavior": "deny", "message": "User denied", "interrupt": False}

options = ClaudeAgentOptions(
    cwd="/path/to/project",
    can_use_tool=permission_handler,
    permission_mode="default",  # Prompt for each tool use
    # Pass through any CLI options the user specified
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Implement the authentication system")
    
    async for message in client.receive_response():
        # Stream to phone via WebSocket
        await broadcast_to_phones(message)
```

### Key SDK Features

| Feature | How We Use It |
|---------|---------------|
| `can_use_tool` callback | Route permission requests to phone, await response |
| `client.interrupt()` | Stop current generation (equivalent to Escape key) |
| `client.query()` | Send user input (text prompts from phone) |
| Session ID in `system.init` | Track sessions, enable resumption |
| `resume` option | Resume session for `wormhole attach` |
| Automatic compaction | SDK handles context window management |
| `permission_mode` | Set to "default" for phone-controlled approval |

### Permission Flow

```
Phone User                    Daemon                      Claude SDK
    │                           │                              │
    │   "Implement auth"        │                              │
    │ ─────────────────────────>│                              │
    │                           │   client.query()             │
    │                           │ ────────────────────────────>│
    │                           │                              │
    │                           │      [Claude working...]     │
    │   AssistantMessage        │                              │
    │ <─────────────────────────│ <────────────────────────────│
    │                           │                              │
    │                           │   can_use_tool("Write",      │
    │                           │     {file_path: "auth.py"})  │
    │   PermissionRequest       │ <────────────────────────────│
    │ <─────────────────────────│                              │
    │                           │      [SDK BLOCKED waiting    │
    │   User taps "Allow"       │       for callback return]   │
    │ ─────────────────────────>│                              │
    │                           │   return {behavior: "allow"} │
    │                           │ ────────────────────────────>│
    │                           │                              │
    │   ToolResult              │      [Tool executes]         │
    │ <─────────────────────────│ <────────────────────────────│
    │                           │                              │
```

### Control Actions

| Action | SDK Method | Phone UI |
|--------|------------|----------|
| Stop | `await client.interrupt()` | 🛑 Stop button |
| Send Input | `await client.query(text)` | Text field + Send |
| Allow Tool | Return `{behavior: "allow"}` | ✅ Allow button |
| Deny Tool | Return `{behavior: "deny"}` | ❌ Deny button |
| Plan Mode | Send `/plan` as query | 📋 Plan toggle |
| Compact | Send `/compact` as query | 🗜️ Compact button |
| Clear | Send `/clear` as query | 🗑️ Clear button |

### Parallel Interactive Session (Attach)

When user runs `wormhole attach <session>`:

1. Daemon looks up Claude's native `session_id` for that wormhole session
2. Spawns: `screen -S wormhole-<name> claude --resume <session_id>`
3. User gets full interactive terminal experience
4. Both phone AND terminal can see/interact with same conversation
5. SDK session continues to route permissions through daemon

This solves the "I'm back at my desk" use case without abandoning the phone session.

---

## Components

### 1. CLI Tool (`wormhole`)

The command-line interface for managing sessions.

#### Commands

```bash
# Start a new Claude Code session
# Accepts ALL standard claude code options (passthrough)
wormhole open [--name <session-name>] [<claude-options>...]

# Examples:
wormhole open --name api-refactor
wormhole open --name frontend --model claude-sonnet-4-5
wormhole open --allowed-tools "Read,Grep,Glob"
wormhole open --add-dir ../shared-lib

# List active sessions on this machine
wormhole list

# Attach to session in terminal (spawns interactive claude --resume)
wormhole attach <session-name>

# Stop a session gracefully
wormhole close <session-name>

# Show daemon status and connection info
wormhole status

# Run the daemon (usually auto-started via systemd/launchd)
wormhole daemon [--port <port>]
```

#### Behavior

- `wormhole open` starts a new `ClaudeSDKClient` instance within the daemon
- **One session per directory**: If a session already exists in the cwd, error with message
- Default port: `7117` (configurable via `WORMHOLE_PORT` env var)
- Session names auto-generate if not provided (e.g., `api-refactor-a3f2`)
- All `<claude-options>` passed through to `ClaudeAgentOptions`
- Working directory captured at session start

### 2. Daemon (Python)

The core service running on each machine.

#### Architecture

```python
# Simplified daemon structure
class WormholeDaemon:
    sessions: dict[str, WormholeSession]  # name -> session
    websocket_server: WebSocketServer
    discovery: MDNSAdvertiser
    
class WormholeSession:
    name: str
    directory: Path
    claude_session_id: str  # From SDK's system.init message
    client: ClaudeSDKClient
    options: ClaudeAgentOptions
    pending_permissions: asyncio.Queue  # Permission requests awaiting phone response
    event_buffer: deque[Message]  # Last 1000 events for sync
    state: SessionState  # working, awaiting_approval, idle, error
```

#### Key Responsibilities

| Function | Description |
|----------|-------------|
| Session Registry | Track all active wormhole sessions, enforce one-per-directory |
| SDK Management | Create/manage `ClaudeSDKClient` instances |
| Permission Routing | `can_use_tool` callback sends to phone, awaits response |
| WebSocket Server | Stream SDK messages to phone, receive commands |
| Event Buffer | Store last 1000 events per session for reconnection sync |
| mDNS Advertisement | Announce `_wormhole._tcp.local` for discovery |

#### Message Types (SDK → Phone)

The daemon forwards SDK messages directly. Key types:

```python
# System initialization (contains session_id)
{
    "type": "system",
    "subtype": "init", 
    "session_id": "abc-123-def",
    "cwd": "/home/user/project",
    "tools": ["Bash", "Read", "Write", ...],
    "model": "claude-sonnet-4-5"
}

# Assistant message (Claude's response)
{
    "type": "assistant",
    "message": {
        "content": [
            {"type": "text", "text": "I'll create the auth module..."},
            {"type": "tool_use", "id": "toolu_123", "name": "Write", 
             "input": {"file_path": "auth.py", "content": "..."}}
        ]
    }
}

# Permission request (daemon-generated wrapper)
{
    "type": "permission_request",
    "request_id": "perm_456",
    "tool_name": "Write",
    "tool_input": {"file_path": "auth.py", "content": "..."},
    "session_name": "api-refactor"
}

# Result (task complete)
{
    "type": "result",
    "subtype": "success",
    "session_id": "abc-123-def",
    "total_cost_usd": 0.0234,
    "usage": {"input_tokens": 1234, "output_tokens": 567}
}
```

#### Message Types (Phone → Daemon)

```python
# Send user input
{
    "type": "input",
    "session": "api-refactor",
    "text": "Now add unit tests"
}

# Respond to permission request
{
    "type": "permission_response",
    "request_id": "perm_456",
    "decision": "allow"  # or "deny"
}

# Control commands
{
    "type": "control",
    "session": "api-refactor",
    "action": "interrupt"  # stop, compact, clear, plan
}

# Request sync (after reconnection)
{
    "type": "sync",
    "session": "api-refactor",
    "last_seen_sequence": 42
}
```

#### State Machine

```
                    ┌─────────────┐
         start ────>│    idle     │<─────────────┐
                    └──────┬──────┘              │
                           │ query()             │
                           ▼                     │
                    ┌─────────────┐              │
              ┌────>│   working   │──────────────┤ result
              │     └──────┬──────┘              │
              │            │ can_use_tool()      │
              │            ▼                     │
              │     ┌─────────────────┐          │
              │     │ awaiting_approval│         │
              │     └──────┬──────────┘          │
              │            │ user responds       │
              └────────────┘                     │
                                                 │
                    ┌─────────────┐              │
                    │    error    │<─────────────┘ on error
                    └─────────────┘
```

### 3. iOS App (Swift)

Native iPhone app using SwiftUI.

#### Core Features

| Feature | Implementation |
|---------|----------------|
| Machine Discovery | `NWBrowser` for Bonjour + manual IP entry |
| WebSocket Client | `URLSessionWebSocketTask` |
| Event Rendering | SwiftUI List with message type formatting |
| Quick Actions | Bottom bar with contextual buttons |
| Voice Input | System dictation (built-in keyboard) |
| Offline Sync | Request events since `last_seen_sequence` on reconnect |

#### Views

1. **MachineListView**: All discovered/saved machines with connection status
2. **SessionListView**: Sessions on selected machine with state badges
3. **SessionView**: Main interaction view with:
   - Event stream (scrollable, auto-scroll to bottom)
   - Permission request cards (when awaiting approval)
   - Quick action bar
   - Text input field with send button + mic

#### Quick Action Bar

Context-sensitive buttons based on session state:

| State | Actions |
|-------|---------|
| `idle` | (input only) |
| `working` | 🛑 Stop |
| `awaiting_approval` | ✅ Allow, ❌ Deny, 📋 View Details |
| Any | 📋 Plan, 🗜️ Compact, 🗑️ Clear |

#### Permission Request Card

When session enters `awaiting_approval`:

```
┌────────────────────────────────────────────┐
│ ⚠️  Permission Required                    │
│                                            │
│ Tool: Write                                │
│ File: src/auth/middleware.py               │
│                                            │
│ Content preview:                           │
│ ┌────────────────────────────────────────┐ │
│ │ from functools import wraps            │ │
│ │ def require_auth(f):                   │ │
│ │     @wraps(f)                          │ │
│ │     def decorated(*args, **kw):        │ │
│ │ ...                                    │ │
│ └────────────────────────────────────────┘ │
│                                            │
│  [  ❌ Deny  ]          [  ✅ Allow  ]     │
└────────────────────────────────────────────┘
```

---

## Protocol Specification

### WebSocket Connection

```
ws://<machine-ip>:7117/ws
```

### Handshake

Client sends immediately after connection:

```json
{
  "type": "hello",
  "client_version": "1.0.0",
  "device_name": "My iPhone"
}
```

Server responds:

```json
{
  "type": "welcome",
  "server_version": "1.0.0",
  "machine_name": "devbox",
  "sessions": [
    {
      "name": "api-refactor",
      "directory": "/home/chris/projects/api",
      "state": "working",
      "claude_session_id": "abc-123",
      "cost_usd": 0.0156,
      "last_activity": "2025-12-31T10:30:00Z"
    }
  ]
}
```

### Subscriptions

Client can subscribe to specific sessions:

```json
{
  "type": "subscribe",
  "sessions": ["api-refactor", "frontend-ui"]
}
```

Or all sessions:

```json
{
  "type": "subscribe",
  "sessions": "*"
}
```

### Event Streaming

Server streams SDK messages with metadata wrapper:

```json
{
  "type": "event",
  "session": "api-refactor",
  "sequence": 42,
  "timestamp": "2025-12-31T10:30:15.123Z",
  "message": { /* SDK message object */ }
}
```

### Reconnection Sync

After reconnect, client requests missed events:

```json
{
  "type": "sync",
  "session": "api-refactor", 
  "last_seen_sequence": 35
}
```

Server responds with buffered events:

```json
{
  "type": "sync_response",
  "session": "api-refactor",
  "events": [
    {"sequence": 36, "timestamp": "...", "message": {...}},
    {"sequence": 37, "timestamp": "...", "message": {...}},
    ...
  ]
}
```

---

## Configuration

### Daemon Configuration

`~/.config/wormhole/config.toml`:

```toml
[daemon]
port = 7117
buffer_size = 1000  # events per session

[discovery]
enabled = true
service_name = "wormhole"

[defaults]
# Default Claude options (can be overridden per-session)
model = "claude-sonnet-4-5"
permission_mode = "default"
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WORMHOLE_PORT` | Daemon port | `7117` |
| `WORMHOLE_BUFFER_SIZE` | Events to buffer | `1000` |
| `ANTHROPIC_API_KEY` | Claude API key | (required) |

---

## File Structure

```
wormhole/
├── README.md
├── pyproject.toml
│
├── daemon/
│   ├── wormhole/
│   │   ├── __init__.py
│   │   ├── __main__.py          # CLI entry point
│   │   ├── daemon.py            # Main daemon class
│   │   ├── session.py           # WormholeSession class
│   │   ├── websocket.py         # WebSocket server
│   │   ├── discovery.py         # mDNS/Bonjour
│   │   ├── permissions.py       # can_use_tool routing
│   │   ├── protocol.py          # Message types
│   │   └── config.py            # Configuration handling
│   │
│   └── tests/
│       ├── test_session.py
│       ├── test_permissions.py
│       └── test_protocol.py
│
├── ios/
│   ├── Wormhole.xcodeproj
│   ├── Wormhole/
│   │   ├── App/
│   │   │   ├── WormholeApp.swift
│   │   │   └── ContentView.swift
│   │   ├── Models/
│   │   │   ├── Machine.swift
│   │   │   ├── Session.swift
│   │   │   └── Message.swift
│   │   ├── Views/
│   │   │   ├── MachineListView.swift
│   │   │   ├── SessionListView.swift
│   │   │   ├── SessionView.swift
│   │   │   ├── EventStreamView.swift
│   │   │   ├── PermissionCard.swift
│   │   │   ├── QuickActionBar.swift
│   │   │   └── SettingsView.swift
│   │   ├── Services/
│   │   │   ├── NetworkService.swift
│   │   │   ├── WebSocketClient.swift
│   │   │   ├── DiscoveryService.swift
│   │   │   └── SessionManager.swift
│   │   └── Resources/
│   │       └── Assets.xcassets
│   └── WormholeTests/
│
└── docs/
    ├── PROTOCOL.md              # Detailed protocol spec
    ├── SETUP.md                 # Installation guide
    └── ARCHITECTURE.md          # Technical deep-dive
```

---

## V1 Scope

### In Scope

| Feature | Priority | Notes |
|---------|----------|-------|
| CLI: `open`, `list`, `attach`, `close`, `status` | Must | Full Claude options passthrough |
| Daemon: SDK-based session management | Must | Using `claude-agent-sdk` |
| Daemon: `can_use_tool` permission routing | Must | Core feature |
| Daemon: WebSocket server | Must | Real-time streaming |
| Daemon: mDNS advertisement | Must | Zero-config discovery |
| Daemon: Event buffering (1000/session) | Must | Reconnection sync |
| Daemon: One session per directory | Must | Conflict prevention |
| Daemon: Auto-compaction (SDK built-in) | Must | Context management |
| iOS: Machine discovery + manual add | Must | |
| iOS: Session list with state badges | Must | |
| iOS: Event stream view | Must | Structured messages |
| iOS: Permission request cards | Must | Allow/Deny UI |
| iOS: Quick action bar | Must | Stop, Plan, Compact, Clear |
| iOS: Text input + voice dictation | Must | |
| iOS: Offline reconnection sync | Must | |
| Parallel attach via `wormhole attach` | Must | Terminal access |

### Out of Scope (V2+)

| Feature | Notes |
|---------|-------|
| Push notifications | Requires APNs, possibly relay server |
| Diff viewer for file changes | Parse tool_use content, render diff |
| Android app | Architecture supports it |
| Authentication | Network trust for V1 |
| End-to-end encryption | Security enhancement |
| Session sharing (multiple phones) | Both see, need conflict resolution |
| Persistent session history | SQLite for event history |
| iPad-optimized layout | iPhone focus for V1 |
| Crash recovery | Leverage Claude's transcript files |

---

## Technical Decisions

### Why Claude Agent SDK (vs. CLI + JSONL)?

| Aspect | SDK Approach | CLI Approach |
|--------|--------------|--------------|
| Permission handling | Native `can_use_tool` callback | Parse output, inject stdin |
| Session management | Built-in `session_id` + `resume` | Track manually |
| Context compaction | Automatic | Manual `/compact` commands |
| Stop/Interrupt | `client.interrupt()` method | Send escape character? |
| Input | `client.query(text)` | Write to stdin pipe |
| Complexity | Clean async Python | Process management, pipes |

The SDK gives us a proper programming interface instead of babysitting a CLI process.

### Why One Session Per Directory?

- Claude Code uses the working directory for context
- Multiple sessions in same dir would have conflicting file states
- Simplifies permission reasoning (which session owns this file?)
- User can have unlimited sessions across different directories

### Why Parallel Interactive Sessions?

Users sometimes need full terminal capabilities:
- Complex interactions the phone can't handle
- Debugging with full context
- Pairing with a colleague

`wormhole attach` spawns `claude --resume <session_id>` in a screen session, giving terminal access to the same conversation the phone is monitoring.

### Why Pure Streaming (No Hooks)?

The SDK's `can_use_tool` callback is cleaner than setting up external hooks:
- No HTTP server for hook callbacks
- No race conditions between hook and SDK
- Single source of truth for permissions
- Simpler deployment

### Event Buffer Strategy

- 1,000 events per session in memory
- Sequence numbers for ordering
- Phone requests sync with `last_seen_sequence`
- Consider SQLite for V2 if users want persistent history

---

## Decisions Log

| # | Question | Decision |
|---|----------|----------|
| 1 | Input format for streaming mode | SDK handles it—use `client.query()` |
| 2 | Permission prompt detection | SDK's `can_use_tool` callback |
| 3 | Control characters (Escape/Shift+Tab) | `client.interrupt()` + slash commands |
| 4 | Attach capability without terminal | Parallel session: `wormhole attach` spawns `claude --resume` |
| 5 | Hung process handling | Backup signal from phone > timeout (user can send interrupt) |
| 6 | Crash recovery | Out of scope for V1 |
| 7 | Multi-session same directory | Not allowed—one session per directory |
| 8 | Hooks vs streaming | Pure streaming via SDK |
| 9 | Context compaction | SDK auto-compacts; phone sees status messages |
| 10 | CLI options | Full passthrough of all Claude Code options |

---

## Success Metrics

- Session start-to-phone-connection under 5 seconds
- Event latency under 200ms
- Permission request → phone display under 500ms
- Successfully approve/reject from phone
- Switch between 3+ sessions without issues
- Reconnect and sync after 10+ minutes offline
- Cost/token tracking visible in app
- `wormhole attach` connects to same conversation

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| SDK `can_use_tool` bugs | Medium | High | Issue #227 shows workarounds; monitor SDK releases |
| SDK hung process | Medium | High | Phone can send interrupt; user-initiated timeout |
| Network reliability | Medium | Medium | Robust reconnection, event buffering |
| iOS app review | Low | High | No private APIs, follows guidelines |
| SDK breaking changes | Medium | Medium | Pin SDK version, monitor changelog |
| Concurrent attach conflicts | Low | Medium | Both see same events; last-write-wins for input |

---

## Development & Testing Strategy

### Philosophy

**Build once, test continuously.** Every component should have tests that:
1. Validate correct behavior during development
2. Catch regressions when upgrading `claude-agent-sdk` versions
3. Enable confident refactoring

**SDK Compatibility Testing**: The Claude Agent SDK is actively developed. Our test suite must detect breaking changes early by testing against both pinned and latest SDK versions in CI.

---

### Recommended Tools

| Category | Tool | Purpose |
|----------|------|---------|
| **Python** | `uv` | Fast package management, lockfiles |
| **Testing** | `pytest` + `pytest-asyncio` | Async test support for SDK integration |
| **Mocking** | `pytest-mock` + `respx` | Mock SDK responses, HTTP/WebSocket |
| **WebSocket Testing** | `websockets` (client mode) | Test daemon's WebSocket server |
| **Coverage** | `pytest-cov` | Ensure test coverage |
| **Linting** | `ruff` | Fast Python linting |
| **Type Checking** | `pyright` | Catch type errors with SDK types |
| **CI** | GitHub Actions | Matrix testing against SDK versions |
| **iOS Testing** | XCTest + Swift Testing | Unit and integration tests |
| **iOS UI Testing** | XCUITest | End-to-end UI automation |
| **iOS Mocking** | Swift mock WebSocket server | Test app without real daemon |

---

### Test Categories

#### 1. Unit Tests (Fast, No Network)
- Pure logic: event buffering, state machine, protocol serialization
- Mock SDK client responses
- Run on every commit

#### 2. Integration Tests (SDK + Daemon)
- Real `ClaudeSDKClient` against daemon
- Test permission flow end-to-end
- Test session lifecycle (create, query, interrupt, close)
- Run with `--integration` flag

#### 3. SDK Compatibility Tests
- Subset of integration tests run against multiple SDK versions
- Matrix: `[pinned-version, latest]`
- Detect API changes, new message types, callback signature changes

#### 4. End-to-End Tests (Full Stack)
- Daemon + WebSocket client (simulating phone)
- Real Claude API calls (use small/cheap prompts)
- Manual or scheduled (expensive)

#### 5. iOS Tests
- Unit: Models, services (mocked network)
- Integration: Real WebSocket to local test server
- UI: XCUITest for critical flows

---

## Implementation Plan

### Phase 1: Project Setup & Core Session (Week 1)

**Goal**: Single SDK session with permission routing, testable without phone.

#### Tasks

1. **Project scaffolding**
   ```bash
   # Claude Code commands
   mkdir -p daemon/wormhole daemon/tests
   uv init daemon
   uv add claude-agent-sdk websockets zeroconf
   uv add --dev pytest pytest-asyncio pytest-mock pytest-cov ruff pyright
   ```

2. **Core types** (`protocol.py`)
   - Define all message types as dataclasses/Pydantic models
   - Phone→Daemon and Daemon→Phone messages
   - Tests: Serialization round-trips

3. **Session wrapper** (`session.py`)
   - `WormholeSession` class wrapping `ClaudeSDKClient`
   - `can_use_tool` callback with async queue
   - Event buffer (deque with sequence numbers)
   - Tests: Mock SDK client, verify state transitions

4. **Permission routing** (`permissions.py`)
   - Async queue for pending permission requests
   - Timeout handling (configurable, default=none/infinite)
   - Tests: Concurrent permission requests, allow/deny responses

5. **Basic WebSocket server** (`websocket.py`)
   - Accept connections, handle hello/welcome
   - Stream events from session
   - Receive permission responses
   - Tests: `websockets` client connects, sends/receives messages

#### Phase 1 Test Suite

```python
# tests/test_session.py
async def test_session_creation():
    """Session initializes with correct state."""
    
async def test_permission_callback_blocks():
    """can_use_tool blocks until response received."""
    
async def test_permission_allow():
    """Allow response unblocks and returns correct result."""
    
async def test_permission_deny():
    """Deny response unblocks with deny result."""

async def test_event_buffer_ordering():
    """Events buffered with correct sequence numbers."""

async def test_event_buffer_overflow():
    """Old events evicted when buffer full."""

# tests/test_websocket.py
async def test_websocket_handshake():
    """Client connects and receives welcome."""

async def test_event_streaming():
    """Events streamed to subscribed clients."""

async def test_permission_request_response():
    """Permission request sent, response received and routed."""
```

#### Phase 1 Deliverable
- `wormhole daemon` runs and accepts WebSocket connections
- Python test client can: connect, receive events, respond to permissions
- All unit tests pass
- Integration test with real SDK (small prompt) passes

---

### Phase 2: CLI & Multi-Session (Week 2)

**Goal**: Full CLI, multiple sessions, one-per-directory enforcement.

#### Tasks

1. **CLI implementation** (`__main__.py`)
   - Use `click` or `typer` for CLI framework
   - Commands: `daemon`, `open`, `list`, `close`, `status`
   - IPC to running daemon (Unix socket or HTTP)
   - Tests: CLI parsing, IPC protocol

2. **Daemon manager** (`daemon.py`)
   - Session registry (dict[name, Session])
   - Directory→session mapping for conflict detection
   - Graceful shutdown
   - Tests: Multi-session lifecycle

3. **One-per-directory enforcement**
   - Check registry before creating session
   - Clear error message with existing session name
   - Tests: Conflict detection and error

4. **Claude options passthrough**
   - Parse CLI args, map to `ClaudeAgentOptions`
   - Support all documented options
   - Tests: Option mapping

5. **Attach command** (`attach.py`)
   - Look up Claude session ID from registry
   - Spawn `screen -S wormhole-<name> claude --resume <id>`
   - Tests: Screen session created (mock subprocess)

#### Phase 2 Test Suite

```python
# tests/test_cli.py
def test_open_creates_session():
    """'wormhole open' creates session in daemon."""

def test_open_duplicate_directory_fails():
    """'wormhole open' in same dir fails with error."""

def test_list_shows_sessions():
    """'wormhole list' returns active sessions."""

def test_close_stops_session():
    """'wormhole close' terminates session gracefully."""

def test_options_passthrough():
    """CLI options passed to ClaudeAgentOptions."""

# tests/test_daemon.py
async def test_multi_session():
    """Multiple sessions run concurrently."""

async def test_session_isolation():
    """Events routed to correct session."""
```

#### Phase 2 Deliverable
- Full CLI works: `wormhole open/list/close/attach/status`
- Multiple sessions supported
- Directory conflict detection works
- All tests pass

---

### Phase 3: Discovery & Sync (Week 3)

**Goal**: mDNS discovery, reconnection sync, production-ready daemon.

#### Tasks

1. **mDNS advertisement** (`discovery.py`)
   - Use `zeroconf` library
   - Advertise `_wormhole._tcp.local`
   - Include machine name, port in TXT records
   - Tests: Service registered (mock zeroconf)

2. **Event sync protocol**
   - Handle `sync` request with `last_seen_sequence`
   - Return buffered events since sequence
   - Tests: Sync after reconnection

3. **Configuration** (`config.py`)
   - Load from `~/.config/wormhole/config.toml`
   - Environment variable overrides
   - Tests: Config loading, precedence

4. **Logging & observability**
   - Structured logging (JSON option)
   - Health endpoint for monitoring
   - Tests: Log output format

5. **Systemd/launchd integration**
   - Service files for auto-start
   - Socket activation (optional)
   - Documentation

#### Phase 3 Test Suite

```python
# tests/test_discovery.py
def test_mdns_advertisement():
    """Service advertised on startup."""

def test_mdns_shutdown():
    """Service unregistered on shutdown."""

# tests/test_sync.py
async def test_sync_returns_missed_events():
    """Sync request returns events after sequence."""

async def test_sync_empty_buffer():
    """Sync request with no missed events."""

async def test_sync_sequence_too_old():
    """Sync request for evicted events."""
```

#### Phase 3 Deliverable
- Daemon discoverable via Bonjour
- Reconnection sync works
- Config file support
- Ready for iOS app integration

---

### Phase 4: iOS App Core (Week 4)

**Goal**: Functional iOS app with discovery and session viewing.

#### Tasks

1. **Project setup**
   - Xcode project with SwiftUI
   - Swift Package dependencies (if any)
   - Test targets configured

2. **Models** (`Models/`)
   - `Machine`, `Session`, `Message` types
   - Codable for JSON parsing
   - Tests: Decoding all message types

3. **WebSocket client** (`Services/WebSocketClient.swift`)
   - `URLSessionWebSocketTask` wrapper
   - Reconnection with exponential backoff
   - Tests: Mock WebSocket server

4. **Discovery service** (`Services/DiscoveryService.swift`)
   - `NWBrowser` for Bonjour
   - Manual machine entry
   - Tests: Mock NWBrowser

5. **Machine list view**
   - Show discovered + saved machines
   - Connection status indicators
   - Tests: View model logic

6. **Session list view**
   - Sessions from connected machine
   - State badges (working, awaiting, idle)
   - Tests: State badge logic

#### Phase 4 Test Suite

```swift
// Tests/MessageDecodingTests.swift
func testDecodeSystemInit() throws { }
func testDecodeAssistantMessage() throws { }
func testDecodePermissionRequest() throws { }
func testDecodeResult() throws { }

// Tests/WebSocketClientTests.swift
func testConnectAndHandshake() async throws { }
func testReconnectionOnDisconnect() async throws { }
func testEventStreaming() async throws { }

// Tests/SessionViewModelTests.swift
func testStateTransitions() { }
func testEventBuffering() { }
```

#### Phase 4 Deliverable
- iOS app discovers machines
- Connects and shows session list
- Unit tests for all models and services

---

### Phase 5: iOS Interaction (Week 5)

**Goal**: Full interaction: permissions, input, quick actions.

#### Tasks

1. **Session view**
   - Event stream (ScrollView with auto-scroll)
   - Message type formatting
   - Tests: Rendering logic

2. **Permission card**
   - Tool name, input preview
   - Allow/Deny buttons
   - Tests: Card state management

3. **Quick action bar**
   - Context-sensitive buttons
   - Stop, Plan, Compact, Clear
   - Tests: Button visibility logic

4. **Text input**
   - Text field with send button
   - Voice dictation (system keyboard)
   - Tests: Input validation

5. **Offline sync**
   - Track `last_seen_sequence`
   - Request sync on reconnection
   - Tests: Sync flow

#### Phase 5 Test Suite

```swift
// Tests/PermissionCardTests.swift
func testAllowSendsResponse() async throws { }
func testDenySendsResponse() async throws { }

// Tests/QuickActionTests.swift
func testStopButtonVisibleWhenWorking() { }
func testPermissionButtonsVisibleWhenAwaiting() { }

// Tests/SyncTests.swift
func testSyncRequestOnReconnect() async throws { }
func testMissedEventsApplied() async throws { }
```

#### Phase 5 Deliverable
- Full phone interaction works
- Approve/deny from phone
- Send messages, stop generation
- Reconnection syncs correctly

---

### Phase 6: Polish & Release (Week 6)

**Goal**: Production quality, documentation, TestFlight.

#### Tasks

1. **Error handling**
   - User-friendly error messages
   - Recovery suggestions
   - Tests: Error scenarios

2. **Edge cases**
   - Daemon restart during active session
   - Network transitions (WiFi↔Cellular)
   - Large message handling
   - Tests: Stress tests

3. **Performance**
   - Profile and optimize
   - Memory usage with many events
   - Tests: Performance benchmarks

4. **Documentation**
   - README with quick start
   - SETUP.md with detailed install
   - PROTOCOL.md for contributors
   - ARCHITECTURE.md for maintainers

5. **CI/CD**
   - GitHub Actions workflow
   - Test matrix (Python 3.11+, SDK versions)
   - iOS build and test

6. **Release**
   - PyPI package for daemon
   - TestFlight build for iOS
   - Beta testing

#### CI Configuration

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]

jobs:
  daemon-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.11", "3.12"]
        sdk-version: ["pinned", "latest"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: |
          if [ "${{ matrix.sdk-version }}" = "latest" ]; then
            uv add claude-agent-sdk@latest
          fi
      - run: uv run pytest --cov

  ios-tests:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - run: xcodebuild test -scheme Wormhole -destination 'platform=iOS Simulator,name=iPhone 15'
```

---

## SDK Version Compatibility

### Pinned Version Strategy

```toml
# pyproject.toml
[project]
dependencies = [
    "claude-agent-sdk>=0.1.0,<0.2.0",  # Pin to minor version
]

[tool.uv]
# Lock file ensures reproducible installs
```

### Compatibility Test Matrix

| SDK Version | Test Status | Notes |
|-------------|-------------|-------|
| 0.1.x (pinned) | ✅ Required | Production baseline |
| latest | ⚠️ Informational | Detect breaking changes |

### Breaking Change Detection

Tests should catch:
- `can_use_tool` callback signature changes
- New required fields in messages
- Removed/renamed message types
- Session management API changes

```python
# tests/test_sdk_compat.py
def test_can_use_tool_signature():
    """Verify can_use_tool callback signature matches expected."""
    import inspect
    from claude_agent_sdk import ClaudeAgentOptions
    # Inspect callback type annotation
    
def test_message_types_exist():
    """Verify expected message types are importable."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, ...
    
def test_client_methods_exist():
    """Verify expected client methods exist."""
    from claude_agent_sdk import ClaudeSDKClient
    assert hasattr(ClaudeSDKClient, 'query')
    assert hasattr(ClaudeSDKClient, 'interrupt')
    assert hasattr(ClaudeSDKClient, 'receive_response')
```

---

## Appendix: SDK Message Types

Reference for phone app developers.

### System Messages

```typescript
interface SystemInit {
  type: "system"
  subtype: "init"
  session_id: string
  cwd: string
  tools: string[]
  model: string
  permission_mode: string
}

interface SystemCompactBoundary {
  type: "system"
  subtype: "compact_boundary"
  session_id: string
  compact_metadata: {
    trigger: "manual" | "auto"
    pre_tokens: number
  }
}
```

### Assistant Messages

```typescript
interface AssistantMessage {
  type: "assistant"
  message: {
    content: ContentBlock[]
  }
}

type ContentBlock = 
  | { type: "text", text: string }
  | { type: "tool_use", id: string, name: string, input: object }
```

### Result Messages

```typescript
interface ResultMessage {
  type: "result"
  subtype: "success" | "error"
  session_id: string
  total_cost_usd: number
  usage: {
    input_tokens: number
    output_tokens: number
  }
}
```

### Wormhole-Specific Messages

```typescript
interface PermissionRequest {
  type: "permission_request"
  request_id: string
  tool_name: string
  tool_input: object
  session_name: string
}

interface PermissionResponse {
  type: "permission_response"
  request_id: string
  decision: "allow" | "deny"
}
```

---

## Companion Documents

For Claude Code to 1-shot this implementation, the following companion documents are provided:

| Document | Purpose |
|----------|---------|
| `CLAUDE.md` | Project-specific instructions for Claude Code (put in project root) |
| `IOS_GUIDE.md` | iOS-specific implementation details, Swift code templates |
| `bootstrap.sh` | Script to scaffold complete project structure with starter code |

### Using These Documents

1. **Run bootstrap first**:
   ```bash
   chmod +x bootstrap.sh
   ./bootstrap.sh wormhole
   cd wormhole
   ```

2. **Copy CLAUDE.md to project root** (already done by bootstrap)

3. **Open in Claude Code**:
   ```bash
   cd wormhole
   claude
   ```

4. **Give Claude Code the task**:
   > "Implement the Wormhole daemon according to the PRD. Start with Phase 1 tasks. Run tests after each component."

### What Claude Code Gets

- Complete `pyproject.toml` with all dependencies
- Pydantic protocol models (fully typed)
- Session class skeleton with `can_use_tool` pattern
- Daemon skeleton with WebSocket handling
- Test fixtures (sample SDK messages)
- Test stubs to fill in
- Acceptance criteria checklist

### Testing Philosophy

Every feature should have a test before moving on. The bootstrap includes:
- `pytest` configuration with async support
- Test fixtures for SDK message types
- Test stubs for each module
- Markers for integration tests (`-m "not integration"` for fast runs)

When Claude Code implements a feature, it should:
1. Write the test first (or fill in the stub)
2. Implement the feature
3. Run `uv run pytest` to verify
4. Move to next feature

---

*Document version: 2.0*  
*Last updated: December 2025*  
*Key update: SDK-based architecture with `can_use_tool` callback for permissions*

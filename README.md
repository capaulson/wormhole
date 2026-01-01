# Wormhole

Remote Claude Code session manager. Monitor and control Claude Code sessions from your iPhone.

## Features

- **Remote Monitoring**: Watch Claude Code work in real-time from your phone
- **Permission Control**: Approve or deny tool usage remotely (file writes, bash commands, etc.)
- **Multi-Session**: Manage multiple Claude Code sessions across projects
- **Auto-Discovery**: Automatically find Wormhole daemons on your local network via Bonjour
- **Quick Actions**: Stop, plan mode, compact context from anywhere

## Architecture

```
┌─────────────┐     WebSocket      ┌──────────────┐
│  iOS App    │◄──────────────────►│   Daemon     │
│  (Swift)    │                    │  (Python)    │
└─────────────┘                    └──────┬───────┘
                                          │
                                          │ Claude Agent SDK
                                          │
                                   ┌──────▼───────┐
                                   │ Claude Code  │
                                   │   Sessions   │
                                   └──────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- Xcode 15+ (for iOS app)
- iOS 17+ device or simulator

### Daemon Setup

```bash
cd daemon
uv sync
uv run wormhole daemon
```

The daemon will start on port 7117 and advertise via mDNS.

### iOS App

Option 1: Generate project with XcodeGen
```bash
cd ios
brew install xcodegen  # if not installed
xcodegen generate
open Wormhole.xcodeproj
```

Option 2: Open the existing project
```bash
open ios/Wormhole.xcodeproj
```

Build and run on your device or simulator (Cmd+R).

## CLI Commands

```bash
# Start the daemon
wormhole daemon [--port 7117] [--no-discovery] [--log-level INFO] [--log-json]

# Open a new Claude Code session in current directory
wormhole open [--name SESSION_NAME] [-- CLAUDE_ARGS]

# List active sessions
wormhole list

# Attach to a session (spawns claude --resume in screen)
wormhole attach SESSION_NAME

# Close a session
wormhole close SESSION_NAME

# Show daemon status
wormhole status
```

## Configuration

The daemon reads configuration from `~/.config/wormhole/config.toml`:

```toml
[daemon]
port = 7117

[discovery]
enabled = true
```

Environment variables override config:
- `WORMHOLE_PORT` - WebSocket port
- `WORMHOLE_DISCOVERY_ENABLED` - Enable/disable mDNS (true/false)

## Development

### Running Tests

Daemon (Python):
```bash
cd daemon
uv run pytest                    # All tests
uv run pytest -m "not integration"  # Unit only
uv run pytest --cov              # With coverage
uv run ruff check .              # Linting
uv run pyright                   # Type checking
```

iOS (Swift):
```bash
cd ios
xcodebuild -scheme Wormhole -destination 'platform=iOS Simulator,name=iPhone 15' test
```

### Project Structure

```
wormhole/
├── daemon/
│   ├── wormhole/
│   │   ├── cli.py           # CLI commands
│   │   ├── daemon.py        # Main daemon
│   │   ├── session.py       # Claude SDK wrapper
│   │   ├── control.py       # CLI-daemon IPC
│   │   ├── protocol.py      # WebSocket messages
│   │   ├── discovery.py     # mDNS advertisement
│   │   ├── logging.py       # Structured logging
│   │   └── config.py        # Configuration
│   └── tests/
│
└── ios/
    └── Wormhole/
        ├── Models/          # Data models
        ├── Views/           # SwiftUI views
        └── Services/        # Networking
```

## WebSocket Protocol

### Client -> Server

| Message | Description |
|---------|-------------|
| `hello` | Initial handshake with client version |
| `subscribe` | Subscribe to session events |
| `input` | Send text to a session |
| `permission_response` | Allow/deny a tool usage |
| `control` | Session actions (interrupt, plan, etc.) |
| `sync` | Request missed events |

### Server -> Client

| Message | Description |
|---------|-------------|
| `welcome` | Server info and session list |
| `event` | Session event (Claude output, tool use) |
| `permission_request` | Tool needs approval |
| `sync_response` | Missed events since sequence |
| `error` | Error message |

## Security

**V1 relies on network trust.** Only run on trusted local networks.

Future versions may add:
- TLS/SSL encryption
- Token-based authentication
- Per-session access controls

## Troubleshooting

### Daemon won't start

Check if port 7117 is in use:
```bash
lsof -i :7117
```

### iOS can't find daemon

1. Ensure both devices are on the same network
2. Check firewall allows port 7117
3. Try manual connection: Settings > Add Machine

### Permission requests not reaching phone

1. Verify WebSocket connection (check daemon logs)
2. Try `wormhole status` to verify daemon is running
3. Check iOS app is subscribed to the session

## License

MIT

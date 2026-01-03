# Wormhole

Remote Claude Code session manager. Monitor and control Claude Code sessions from your iPhone.

## Features

- **Remote Monitoring**: Watch Claude Code work in real-time from your phone
- **Permission Control**: Approve or deny tool usage remotely (file writes, bash commands, etc.)
- **Multi-Session**: Manage multiple Claude Code sessions across projects
- **Auto-Discovery**: Automatically find Wormhole daemons on your local network via Bonjour/Avahi
- **Quick Actions**: Stop, interrupt, or send messages from anywhere
- **Cross-Platform**: Runs on macOS and Linux

## Requirements

- **macOS** or **Linux** with Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- Claude Code CLI installed and authenticated (`claude` command)
- iPhone running iOS 17+

## Installation

### 1. Install the Daemon

```bash
# Clone the repository
git clone https://github.com/capaulson/wormhole.git
cd wormhole/daemon

# Install system-wide (recommended)
uv tool install -e .

# Or just install dependencies for local use
uv sync
```

### Linux Additional Setup

On Linux, install Avahi for device discovery:

```bash
# Debian/Ubuntu
sudo apt install avahi-daemon
sudo systemctl enable --now avahi-daemon

# Fedora/RHEL
sudo dnf install avahi
sudo systemctl enable --now avahi-daemon

# Arch
sudo pacman -S avahi
sudo systemctl enable --now avahi-daemon
```

### 2. Install the iOS App

**Option A: Build from source**
```bash
cd ios
brew install xcodegen  # if not installed
xcodegen generate
open Wormhole.xcodeproj
```
Then build and run on your device (Cmd+R in Xcode).

**Option B: TestFlight** (coming soon)

## Usage

### Start the Daemon

The daemon **auto-starts** when you run any wormhole command. You can also start it manually:

```bash
wormhole daemon
```

The daemon starts on port 7117 and advertises itself via Bonjour/Avahi. You should see:
```
Starting Wormhole daemon on port 7117...
Wormhole daemon ready (port=7117, control_socket=/tmp/wormhole.sock)
```

#### Install as a System Service (Optional)

For automatic startup on login:

```bash
# Install and enable the service
wormhole service install

# Check service status
wormhole service status

# Other service commands
wormhole service start
wormhole service stop
wormhole service logs
wormhole service uninstall
```

This uses **launchd** on macOS and **systemd** on Linux.

### Create a Session

In a new terminal, navigate to your project and create a session:

```bash
cd ~/my-project
wormhole open --name my-project
```

### Connect from iPhone

1. Open the Wormhole app on your iPhone
2. Your Mac should appear automatically (same WiFi network)
3. Tap to connect
4. You'll see your session listed - tap to open it

### Send Messages & Approve Permissions

- Type messages in the text field at the bottom
- When Claude needs to run a command or write a file, you'll see a permission card
- Tap **Allow** or **Deny** to respond

### Use Both CLI and iPhone Together

Wormhole supports **dual-mode** operation - you can use the CLI and iOS app simultaneously:

```bash
# Attach to a session in your terminal
wormhole attach my-project
```

This drops you directly into the Claude CLI. Both interfaces share the same session:
- **CLI**: Full interactive Claude experience in your terminal
- **iOS**: Monitor progress, send messages, approve permissions remotely

Messages sent from either interface appear in both. Use the CLI when at your desk, switch to your phone when you walk away.

## CLI Reference

```bash
# Start the daemon (run once, keeps running)
wormhole daemon

# Create a new session in current directory
wormhole open --name SESSION_NAME

# List all active sessions
wormhole list

# Close a session
wormhole close SESSION_NAME

# Check daemon status
wormhole status

# Attach to session in terminal (for direct interaction)
wormhole attach SESSION_NAME

# Service management (install for auto-start on login)
wormhole service install    # Install as system service
wormhole service uninstall  # Remove system service
wormhole service status     # Check service and mDNS status
wormhole service logs -f    # Follow daemon logs
```

### Session Options

Pass Claude CLI options when creating a session:

```bash
# Skip permission prompts (use with caution!)
wormhole open --name my-session --dangerously-skip-permissions

# Use a specific model
wormhole open --name my-session --model sonnet

# Set a cost limit
wormhole open --name my-session --max-budget-usd 1.00

# Limit conversation turns
wormhole open --name my-session --max-turns 10
```

### Daemon Options

```bash
wormhole daemon [OPTIONS]

Options:
  --port INTEGER      WebSocket port (default: 7117)
  --no-discovery      Disable Bonjour/Avahi advertisement
  --log-level TEXT    Log level: DEBUG, INFO, WARNING, ERROR
  --log-json          Output logs as JSON
```

## Configuration

Create `~/.config/wormhole/config.toml` for persistent settings:

```toml
[daemon]
port = 7117

[discovery]
enabled = true
```

Environment variables override config file:
- `WORMHOLE_PORT` - WebSocket port
- `WORMHOLE_DISCOVERY_ENABLED` - Enable/disable Bonjour (true/false)

## Troubleshooting

### Daemon won't start: "Address already in use"

Another process is using port 7117:
```bash
# Find what's using the port
lsof -i :7117          # macOS
ss -tlnp | grep 7117   # Linux

# Kill it or use a different port
wormhole daemon --port 7118
```

### iPhone can't find the daemon

1. Make sure both devices are on the **same WiFi network**
2. Check your firewall allows incoming connections on port 7117
3. Try adding the machine manually: tap **+** in the app and enter your machine's IP address

To find your IP:
```bash
# macOS
ipconfig getifaddr en0

# Linux
hostname -I | awk '{print $1}'
```

### Linux: mDNS Discovery Not Working

Check Avahi is running:
```bash
# Check status
wormhole service status

# If Avahi not running:
sudo systemctl start avahi-daemon
sudo systemctl enable avahi-daemon

# Verify mDNS is working
avahi-browse -a
```

### Sessions not appearing

1. Make sure the daemon is running (`wormhole status`)
2. Check you created a session (`wormhole list`)
3. In the iOS app, pull down to refresh the session list

### Permission requests not showing up

1. Verify you're subscribed to the session (tap on it in the app)
2. Check the daemon logs for WebSocket connection status
3. Try disconnecting and reconnecting in the app

## Security Note

Wormhole currently relies on network trust - anyone on your local network can connect. Only run on trusted networks (home, office). Future versions will add authentication.

## License

MIT

"""Platform detection and service management utilities."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

ServiceManager = Literal["launchd", "systemd", "none"]


def is_macos() -> bool:
    """Check if running on macOS."""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """Check if running on Linux."""
    return sys.platform == "linux"


def get_service_manager() -> ServiceManager:
    """Detect the system's service manager."""
    if is_macos():
        return "launchd"
    if is_linux() and Path("/run/systemd/system").exists():
        return "systemd"
    return "none"


def check_mdns_support() -> tuple[bool, str]:
    """Check if mDNS/Bonjour is available on this system.

    Returns:
        Tuple of (is_supported, message)
    """
    if is_macos():
        # macOS has Bonjour built-in
        return True, "Bonjour available (built-in)"

    elif is_linux():
        # Linux needs Avahi
        # First check if avahi-daemon exists
        if not shutil.which("avahi-daemon"):
            return False, "Avahi not installed. Install with: sudo apt install avahi-daemon"

        # Check if systemd is managing avahi
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "avahi-daemon"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip() == "active":
                return True, "Avahi daemon running"
            else:
                return (
                    False,
                    "Avahi daemon not running. Start with: sudo systemctl start avahi-daemon",
                )
        except FileNotFoundError:
            # No systemctl, try checking if process is running
            try:
                result = subprocess.run(
                    ["pgrep", "-x", "avahi-daemon"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True, "Avahi daemon running"
                return False, "Avahi daemon not running"
            except FileNotFoundError:
                return False, "Cannot determine Avahi status"
        except subprocess.TimeoutExpired:
            return False, "Timeout checking Avahi status"

    return False, f"Unsupported platform: {sys.platform}"


# === launchd (macOS) ===

def get_launchd_plist_path() -> Path:
    """Get the launchd plist path."""
    return Path.home() / "Library/LaunchAgents/com.wormhole.daemon.plist"


def get_launchd_plist_content() -> str:
    """Generate launchd plist content."""
    wormhole_path = shutil.which("wormhole") or "/usr/local/bin/wormhole"
    data_dir = Path.home() / ".local/share/wormhole"
    log_file = data_dir / "daemon.log"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wormhole.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{wormhole_path}</string>
        <string>daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
    <key>WorkingDirectory</key>
    <string>{data_dir}</string>
</dict>
</plist>
"""


def launchd_is_installed() -> bool:
    """Check if launchd service is installed."""
    return get_launchd_plist_path().exists()


def launchd_install() -> tuple[bool, str]:
    """Install launchd service."""
    plist_path = get_launchd_plist_path()

    if plist_path.exists():
        return False, "Service already installed"

    # Create LaunchAgents directory if needed
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    # Write plist
    plist_path.write_text(get_launchd_plist_content())

    # Load the service
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, "Service installed and started"
    else:
        return False, f"Service installed but failed to start: {result.stderr}"


def launchd_uninstall() -> tuple[bool, str]:
    """Uninstall launchd service."""
    plist_path = get_launchd_plist_path()

    if not plist_path.exists():
        return False, "Service not installed"

    # Unload the service
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )

    # Remove plist
    plist_path.unlink()
    return True, "Service uninstalled"


def launchd_start() -> tuple[bool, str]:
    """Start launchd service."""
    if not launchd_is_installed():
        return False, "Service not installed"

    result = subprocess.run(
        ["launchctl", "start", "com.wormhole.daemon"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, "Service started"
    return False, f"Failed to start: {result.stderr}"


def launchd_stop() -> tuple[bool, str]:
    """Stop launchd service."""
    if not launchd_is_installed():
        return False, "Service not installed"

    result = subprocess.run(
        ["launchctl", "stop", "com.wormhole.daemon"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, "Service stopped"
    return False, f"Failed to stop: {result.stderr}"


def launchd_status() -> tuple[bool, str]:
    """Get launchd service status."""
    if not launchd_is_installed():
        return False, "Service not installed"

    result = subprocess.run(
        ["launchctl", "list", "com.wormhole.daemon"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, "Service running"
    return False, "Service stopped"


# === systemd (Linux) ===

def get_systemd_unit_path() -> Path:
    """Get the systemd user unit path."""
    return Path.home() / ".config/systemd/user/wormhole.service"


def get_systemd_unit_content() -> str:
    """Generate systemd unit file content."""
    wormhole_path = shutil.which("wormhole") or "/usr/local/bin/wormhole"

    return f"""[Unit]
Description=Wormhole Daemon - Remote Claude Code Session Manager
Documentation=https://github.com/anthropics/wormhole
After=network.target avahi-daemon.service
Wants=avahi-daemon.service

[Service]
Type=simple
ExecStart={wormhole_path} daemon
Restart=always
RestartSec=5
Environment=PATH={os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}

[Install]
WantedBy=default.target
"""


def systemd_is_installed() -> bool:
    """Check if systemd service is installed."""
    return get_systemd_unit_path().exists()


def systemd_install() -> tuple[bool, str]:
    """Install systemd user service."""
    unit_path = get_systemd_unit_path()

    if unit_path.exists():
        return False, "Service already installed"

    # Create directory if needed
    unit_path.parent.mkdir(parents=True, exist_ok=True)

    # Write unit file
    unit_path.write_text(get_systemd_unit_content())

    # Reload systemd user daemon
    result = subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Failed to reload systemd: {result.stderr}"

    # Enable the service
    result = subprocess.run(
        ["systemctl", "--user", "enable", "wormhole.service"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Failed to enable service: {result.stderr}"

    # Start the service
    result = subprocess.run(
        ["systemctl", "--user", "start", "wormhole.service"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, "Service installed, enabled, and started"
    return False, f"Service installed but failed to start: {result.stderr}"


def systemd_uninstall() -> tuple[bool, str]:
    """Uninstall systemd user service."""
    unit_path = get_systemd_unit_path()

    if not unit_path.exists():
        return False, "Service not installed"

    # Stop the service
    subprocess.run(
        ["systemctl", "--user", "stop", "wormhole.service"],
        capture_output=True,
    )

    # Disable the service
    subprocess.run(
        ["systemctl", "--user", "disable", "wormhole.service"],
        capture_output=True,
    )

    # Remove unit file
    unit_path.unlink()

    # Reload systemd
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
    )

    return True, "Service uninstalled"


def systemd_start() -> tuple[bool, str]:
    """Start systemd service."""
    if not systemd_is_installed():
        return False, "Service not installed"

    result = subprocess.run(
        ["systemctl", "--user", "start", "wormhole.service"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, "Service started"
    return False, f"Failed to start: {result.stderr}"


def systemd_stop() -> tuple[bool, str]:
    """Stop systemd service."""
    if not systemd_is_installed():
        return False, "Service not installed"

    result = subprocess.run(
        ["systemctl", "--user", "stop", "wormhole.service"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return True, "Service stopped"
    return False, f"Failed to stop: {result.stderr}"


def systemd_status() -> tuple[bool, str]:
    """Get systemd service status."""
    if not systemd_is_installed():
        return False, "Service not installed"

    result = subprocess.run(
        ["systemctl", "--user", "is-active", "wormhole.service"],
        capture_output=True,
        text=True,
    )

    status = result.stdout.strip()
    if status == "active":
        return True, "Service running"
    return False, f"Service {status}"


def systemd_logs(follow: bool = False, lines: int = 50) -> subprocess.Popen[bytes] | str:
    """Get systemd service logs.

    If follow=True, returns a Popen object for streaming.
    Otherwise returns the log output as a string.
    """
    cmd = ["journalctl", "--user", "-u", "wormhole.service", "-n", str(lines)]

    if follow:
        cmd.append("-f")
        return subprocess.Popen(cmd)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

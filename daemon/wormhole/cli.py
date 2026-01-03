"""CLI commands for Wormhole."""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from wormhole.control import (
    CloseSessionRequest,
    ErrorResponse,
    GetStatusRequest,
    ListSessionsRequest,
    OpenSessionRequest,
    get_socket_path,
    send_control_request_sync,
)


def get_daemon_paths() -> tuple[Path, Path, Path]:
    """Get paths for daemon files (data_dir, pid_file, log_file)."""
    data_dir = Path.home() / ".local/share/wormhole"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, data_dir / "daemon.pid", data_dir / "daemon.log"


def kill_process_on_port(port: int) -> bool:
    """Kill any process using the specified port. Returns True if a process was killed."""
    import platform

    try:
        if platform.system() == "Darwin":
            # macOS: use lsof to find process
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                for pid_str in pids:
                    try:
                        pid = int(pid_str.strip())
                        os.kill(pid, signal.SIGTERM)
                        click.echo(f"Killed existing process {pid} on port {port}")
                    except (ValueError, ProcessLookupError):
                        pass
                # Give it a moment to die
                time.sleep(0.5)
                return True
        else:
            # Linux: use ss or netstat
            result = subprocess.run(
                ["ss", "-tlnp", f"sport = :{port}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                # Parse output to find PIDs
                import re
                for line in result.stdout.split("\n"):
                    match = re.search(r"pid=(\d+)", line)
                    if match:
                        try:
                            pid = int(match.group(1))
                            os.kill(pid, signal.SIGTERM)
                            click.echo(f"Killed existing process {pid} on port {port}")
                        except (ValueError, ProcessLookupError):
                            pass
                time.sleep(0.5)
                return True
    except FileNotFoundError:
        # lsof or ss not available
        pass

    return False


def is_daemon_running() -> bool:
    """Check if daemon is running."""
    socket_path = get_socket_path()
    if not socket_path.exists():
        return False

    # Socket exists, try to connect
    from wormhole.control import StatusResponse
    response = send_control_request_sync(GetStatusRequest())
    return isinstance(response, StatusResponse)


def start_daemon_background() -> bool:
    """Start daemon as a background process. Returns True if started successfully."""
    _, pid_file, log_file = get_daemon_paths()

    # Find the wormhole executable
    wormhole_cmd = sys.argv[0]
    if not os.path.isabs(wormhole_cmd):
        import shutil
        wormhole_cmd = shutil.which("wormhole") or sys.executable

    # Build command - if we're running via python -m, use that
    if "wormhole" in wormhole_cmd:
        cmd = [wormhole_cmd, "daemon"]
    else:
        cmd = [sys.executable, "-m", "wormhole", "daemon"]

    # Start daemon with output redirected to log file
    with open(log_file, "a") as log:
        process = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # Detach from terminal
        )

    # Write PID file
    pid_file.write_text(str(process.pid))

    # Wait for socket to appear (up to 30 seconds - session restoration can be slow)
    socket_path = get_socket_path()
    for _ in range(300):
        if socket_path.exists() and is_daemon_running():
            return True
        time.sleep(0.1)

    return False


def ensure_daemon_running(silent: bool = False) -> bool:
    """Ensure daemon is running, starting it if necessary.

    Returns True if daemon is running (was already running or started successfully).
    """
    if is_daemon_running():
        return True

    if not silent:
        click.echo("Starting Wormhole daemon in background...")

    if start_daemon_background():
        if not silent:
            click.secho("Daemon started", fg="green")
        return True
    else:
        click.secho("Failed to start daemon", fg="red", err=True)
        return False


def stop_daemon() -> bool:
    """Stop the daemon if running. Returns True if stopped."""
    _, pid_file, _ = get_daemon_paths()

    if not is_daemon_running():
        return True

    # Try to get PID from file
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            # Wait for it to stop
            for _ in range(30):
                try:
                    os.kill(pid, 0)  # Check if still running
                    time.sleep(0.1)
                except ProcessLookupError:
                    pid_file.unlink(missing_ok=True)
                    return True
        except (ValueError, ProcessLookupError):
            pass

    # Fallback: can't stop cleanly
    return False


def generate_session_name(directory: Path) -> str:
    """Generate a session name from directory."""
    import hashlib

    name = directory.name
    # Add short hash to avoid conflicts
    hash_suffix = hashlib.sha256(str(directory).encode()).hexdigest()[:4]
    return f"{name}-{hash_suffix}"


@click.group()
@click.version_option()
def main() -> None:
    """Wormhole - Remote Claude Code session manager."""
    pass


@main.command()
@click.option("--port", default=7117, help="Port to listen on")
@click.option("--no-discovery", is_flag=True, help="Disable mDNS discovery")
@click.option("--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")
@click.option("--log-json", is_flag=True, help="Output logs as JSON")
def daemon(port: int, no_discovery: bool, log_level: str, log_json: bool) -> None:
    """Start the Wormhole daemon."""
    from wormhole.daemon import WormholeDaemon
    from wormhole.log_config import setup_logging

    setup_logging(level=log_level, json_output=log_json)

    # Kill any existing process using this port
    kill_process_on_port(port)

    click.echo(f"Starting Wormhole daemon on port {port}...")
    d = WormholeDaemon(port=port, enable_discovery=not no_discovery)
    asyncio.run(d.run())


@main.command("open")
@click.option("--name", default=None, help="Session name")
@click.argument("claude_args", nargs=-1)
def open_session(name: str | None, claude_args: tuple[str, ...]) -> None:
    """Start a new Claude Code session.

    Any additional arguments are passed through to Claude.
    """
    # Auto-start daemon if needed
    if not ensure_daemon_running():
        sys.exit(1)

    cwd = Path.cwd()

    if name is None:
        name = generate_session_name(cwd)

    # Convert claude args to options dict
    options: dict[str, str | list[str] | None] = {}
    i = 0
    while i < len(claude_args):
        arg = claude_args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            # Check if next arg is a value or another flag
            if i + 1 < len(claude_args) and not claude_args[i + 1].startswith("--"):
                options[key] = claude_args[i + 1]
                i += 2
            else:
                options[key] = None
                i += 1
        else:
            i += 1

    request = OpenSessionRequest(
        name=name,
        directory=str(cwd),
        options=options if options else None,
    )

    response = send_control_request_sync(request)

    if isinstance(response, ErrorResponse):
        click.secho(f"Error: {response.message}", fg="red", err=True)
        sys.exit(1)
    else:
        click.secho(f"Session '{name}' created", fg="green")
        click.echo(f"  Directory: {cwd}")
        if claude_args:
            click.echo(f"  Claude args: {' '.join(claude_args)}")


@main.command("list")
def list_sessions() -> None:
    """List active sessions."""
    from wormhole.control import SessionListResponse

    # Auto-start daemon if needed
    if not ensure_daemon_running():
        sys.exit(1)

    request = ListSessionsRequest()
    response = send_control_request_sync(request)

    if isinstance(response, ErrorResponse):
        click.secho(f"Error: {response.message}", fg="red", err=True)
        sys.exit(1)

    if not isinstance(response, SessionListResponse):
        click.secho("Unexpected response type", fg="red", err=True)
        sys.exit(1)

    if not response.sessions:
        click.echo("No active sessions")
        return

    click.echo("Active sessions:")
    for session in response.sessions:
        state_colors = {
            "idle": "blue",
            "working": "yellow",
            "awaiting_approval": "magenta",
            "error": "red",
        }
        state_color = state_colors.get(session.state, "white")
        click.echo(
            f"  {session.name} "
            f"[{click.style(session.state, fg=state_color)}] "
            f"- {session.directory}"
        )
        if session.cost_usd > 0:
            click.echo(f"    Cost: ${session.cost_usd:.4f}")


@main.command()
@click.argument("session_name")
@click.option("--screen", "use_screen", is_flag=True, help="Run in a screen session")
def attach(session_name: str, use_screen: bool) -> None:
    """Attach to a session in the Claude CLI.

    Opens an interactive Claude session that shares state with the iOS app.
    Both interfaces can send messages and see the conversation.

    Use --screen to run in a detachable screen session.
    """
    from wormhole.control import SessionInfoResponse, SessionListResponse

    # Auto-start daemon if needed
    if not ensure_daemon_running():
        sys.exit(1)

    # First, get the session info
    list_request = ListSessionsRequest()
    list_response = send_control_request_sync(list_request)

    if isinstance(list_response, ErrorResponse):
        click.secho(f"Error: {list_response.message}", fg="red", err=True)
        sys.exit(1)

    if not isinstance(list_response, SessionListResponse):
        click.secho("Unexpected response type", fg="red", err=True)
        sys.exit(1)

    # Find the session
    session: SessionInfoResponse | None = None
    for s in list_response.sessions:
        if s.name == session_name:
            session = s
            break

    if not session:
        click.secho(f"Error: Session not found: {session_name}", fg="red", err=True)
        sys.exit(1)

    if not session.claude_session_id:
        click.secho(
            "Error: Session has no Claude session ID yet. "
            "Send a query first to initialize.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    claude_session_id = session.claude_session_id
    session_dir = session.directory

    # Change to session directory
    os.chdir(session_dir)

    if use_screen:
        # Spawn claude --resume in a screen session
        screen_name = f"wormhole-{session_name}"

        # Check if screen session already exists
        result = subprocess.run(
            ["screen", "-list", screen_name],
            capture_output=True,
            text=True,
        )

        if screen_name in result.stdout:
            click.echo(f"Attaching to existing screen session '{screen_name}'...")
            os.execvp("screen", ["screen", "-r", screen_name])
        else:
            click.echo(f"Creating screen session '{screen_name}'...")
            os.execvp(
                "screen",
                ["screen", "-S", screen_name, "claude", "--resume", claude_session_id],
            )
    else:
        # Direct attach - run Claude CLI as subprocess
        # Using subprocess.run instead of os.execvp so the wormhole session
        # stays alive in the daemon when Claude exits
        click.echo(f"Attaching to session '{session_name}' in {session_dir}")
        click.echo(f"Session ID: {claude_session_id}")
        click.echo("─" * 50)
        result = subprocess.run(["claude", "--resume", claude_session_id])
        click.echo("─" * 50)
        click.echo(
            f"Claude exited (code {result.returncode}). Session '{session_name}' remains active."
        )


@main.command()
@click.argument("session_name")
def close(session_name: str) -> None:
    """Close a session."""
    # Auto-start daemon if needed (to access persisted sessions)
    if not ensure_daemon_running():
        sys.exit(1)

    request = CloseSessionRequest(name=session_name)
    response = send_control_request_sync(request)

    if isinstance(response, ErrorResponse):
        click.secho(f"Error: {response.message}", fg="red", err=True)
        sys.exit(1)
    else:
        click.secho(f"Session '{session_name}' closed", fg="green")


@main.command()
def status() -> None:
    """Show daemon status and connection info."""
    from wormhole.control import StatusResponse

    request = GetStatusRequest()
    response = send_control_request_sync(request)

    if isinstance(response, ErrorResponse):
        click.secho("Daemon: not running", fg="red")
        click.echo(f"  {response.message}")
        sys.exit(1)

    if not isinstance(response, StatusResponse):
        click.secho("Unexpected response type", fg="red", err=True)
        sys.exit(1)

    click.secho("Daemon: running", fg="green")
    click.echo(f"  Machine: {response.machine_name}")
    click.echo(f"  Port: {response.port}")
    click.echo(f"  Sessions: {response.session_count}")
    click.echo(f"  Connected clients: {response.connected_clients}")


@main.command()
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Shell type (auto-detected if not specified)",
)
@click.option("--install", is_flag=True, help="Install completion to shell config")
def completion(shell: str | None, install: bool) -> None:
    """Generate shell completion script.

    Examples:

    \b
      # Print zsh completion script
      wormhole completion --shell zsh

    \b
      # Install completion for your current shell
      wormhole completion --install

    \b
      # Manual installation (zsh)
      wormhole completion --shell zsh > ~/.wormhole-complete.zsh
      echo 'source ~/.wormhole-complete.zsh' >> ~/.zshrc
    """

    # Auto-detect shell if not specified
    if shell is None:
        shell_path = os.environ.get("SHELL", "")
        if "zsh" in shell_path:
            shell = "zsh"
        elif "fish" in shell_path:
            shell = "fish"
        else:
            shell = "bash"

    # Generate completion script using Click's built-in support
    env = {**os.environ, "_WORMHOLE_COMPLETE": f"{shell}_source"}
    result = subprocess.run(
        ["wormhole"],
        env=env,
        capture_output=True,
        text=True,
    )

    completion_script = result.stdout

    # For zsh, wrap with compinit check to ensure completion system is loaded
    if shell == "zsh":
        completion_script = f"""\
# Wormhole CLI completion for zsh
# Ensure completion system is initialized
autoload -Uz compinit 2>/dev/null
if [[ -z "$_comps" ]]; then
    compinit -u 2>/dev/null
fi

{completion_script}
"""

    if install:
        # Determine config file and install
        home = Path.home()
        completion_file = home / ".wormhole-complete"

        if shell == "zsh":
            config_file = home / ".zshrc"
            completion_file = completion_file.with_suffix(".zsh")
            source_line = f"source {completion_file}\n"
        elif shell == "fish":
            config_dir = home / ".config" / "fish" / "completions"
            config_dir.mkdir(parents=True, exist_ok=True)
            completion_file = config_dir / "wormhole.fish"
            source_line = None  # Fish auto-loads from completions dir
        else:  # bash
            config_file = home / ".bashrc"
            completion_file = completion_file.with_suffix(".bash")
            source_line = f"source {completion_file}\n"

        # Write completion script
        completion_file.write_text(completion_script)
        click.echo(f"Wrote completion script to {completion_file}")

        # Add source line to config if needed
        if source_line:
            config_content = config_file.read_text() if config_file.exists() else ""
            if str(completion_file) not in config_content:
                with open(config_file, "a") as f:
                    f.write(f"\n# Wormhole CLI completion\n{source_line}")
                click.echo(f"Added source line to {config_file}")
            else:
                click.echo(f"Source line already in {config_file}")

        click.secho(f"\n✓ Completion installed for {shell}!", fg="green")
        click.echo("  Restart your shell or run:")
        if shell == "fish":
            click.echo(f"    source {completion_file}")
        else:
            click.echo(f"    source {config_file}")
    else:
        # Just print the script
        click.echo(completion_script)


# === Service Management Commands ===


@main.group()
def service() -> None:
    """Manage the Wormhole daemon as a system service.

    Install the daemon for automatic startup on login.
    Supports launchd (macOS) and systemd (Linux).
    """
    pass


@service.command("install")
def service_install() -> None:
    """Install daemon as a system service (starts on login)."""
    from wormhole.platform import (
        get_launchd_plist_path,
        get_service_manager,
        get_systemd_unit_path,
        launchd_install,
        launchd_is_installed,
        systemd_install,
        systemd_is_installed,
    )

    manager = get_service_manager()

    if manager == "launchd":
        if launchd_is_installed():
            click.secho("Service already installed", fg="yellow")
            click.echo(f"  Plist: {get_launchd_plist_path()}")
            click.echo("  Run 'wormhole service uninstall' to remove it first")
            return

        success, msg = launchd_install()
        if success:
            click.secho(msg, fg="green")
            click.echo("  Daemon will now start automatically on login")
        else:
            click.secho(msg, fg="yellow")

    elif manager == "systemd":
        if systemd_is_installed():
            click.secho("Service already installed", fg="yellow")
            click.echo(f"  Unit: {get_systemd_unit_path()}")
            click.echo("  Run 'wormhole service uninstall' to remove it first")
            return

        success, msg = systemd_install()
        if success:
            click.secho(msg, fg="green")
            click.echo("  Daemon will now start automatically on login")
            click.echo(
                "  Note: Run 'loginctl enable-linger $USER' for service to run without login"
            )
        else:
            click.secho(f"Failed: {msg}", fg="red", err=True)

    else:
        click.secho("No supported service manager found", fg="red", err=True)
        click.echo("  macOS: launchd (built-in)")
        click.echo("  Linux: systemd")


@service.command("uninstall")
def service_uninstall() -> None:
    """Uninstall the system service."""
    from wormhole.platform import (
        get_service_manager,
        launchd_is_installed,
        launchd_uninstall,
        systemd_is_installed,
        systemd_uninstall,
    )

    manager = get_service_manager()

    if manager == "launchd":
        if not launchd_is_installed():
            click.echo("Service not installed")
            return

        success, msg = launchd_uninstall()
        if success:
            click.secho(msg, fg="green")
        else:
            click.secho(msg, fg="red", err=True)

    elif manager == "systemd":
        if not systemd_is_installed():
            click.echo("Service not installed")
            return

        success, msg = systemd_uninstall()
        if success:
            click.secho(msg, fg="green")
        else:
            click.secho(msg, fg="red", err=True)

    else:
        click.echo("No supported service manager found")


@service.command("start")
def service_start() -> None:
    """Start the daemon service."""
    from wormhole.platform import (
        get_service_manager,
        launchd_is_installed,
        launchd_start,
        systemd_is_installed,
        systemd_start,
    )

    manager = get_service_manager()

    if manager == "launchd":
        if not launchd_is_installed():
            if ensure_daemon_running():
                click.secho("Daemon started (not installed as service)", fg="green")
            return

        success, msg = launchd_start()
        if success:
            click.secho(msg, fg="green")
        else:
            click.secho(msg, fg="red", err=True)

    elif manager == "systemd":
        if not systemd_is_installed():
            if ensure_daemon_running():
                click.secho("Daemon started (not installed as service)", fg="green")
            return

        success, msg = systemd_start()
        if success:
            click.secho(msg, fg="green")
        else:
            click.secho(msg, fg="red", err=True)

    else:
        if ensure_daemon_running():
            click.secho("Daemon started", fg="green")


@service.command("stop")
def service_stop() -> None:
    """Stop the daemon service."""
    from wormhole.platform import (
        get_service_manager,
        launchd_is_installed,
        launchd_stop,
        systemd_is_installed,
        systemd_stop,
    )

    manager = get_service_manager()

    if manager == "launchd" and launchd_is_installed():
        success, msg = launchd_stop()
        if success:
            click.secho(msg, fg="green")
        else:
            click.secho(msg, fg="red", err=True)

    elif manager == "systemd" and systemd_is_installed():
        success, msg = systemd_stop()
        if success:
            click.secho(msg, fg="green")
        else:
            click.secho(msg, fg="red", err=True)

    else:
        if stop_daemon():
            click.secho("Daemon stopped", fg="green")
        else:
            click.secho("Failed to stop daemon", fg="red", err=True)


@service.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def service_logs(follow: bool, lines: int) -> None:
    """View daemon logs."""
    from wormhole.platform import (
        get_service_manager,
        systemd_is_installed,
        systemd_logs,
    )

    manager = get_service_manager()

    # On Linux with systemd, use journalctl if service is installed
    if manager == "systemd" and systemd_is_installed():
        if follow:
            # Stream logs
            proc = systemd_logs(follow=True, lines=lines)
            try:
                proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
        else:
            output = systemd_logs(follow=False, lines=lines)
            click.echo(output)
        return

    # Fall back to log file
    _, _, log_file = get_daemon_paths()

    if not log_file.exists():
        click.echo("No logs yet")
        return

    if follow:
        os.execvp("tail", ["tail", "-f", str(log_file)])
    else:
        result = subprocess.run(
            ["tail", f"-{lines}", str(log_file)],
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)


@service.command("status")
def service_status() -> None:
    """Show service status."""
    from wormhole.platform import (
        check_mdns_support,
        get_launchd_plist_path,
        get_service_manager,
        get_systemd_unit_path,
        launchd_is_installed,
        launchd_status,
        systemd_is_installed,
        systemd_status,
    )

    manager = get_service_manager()
    running = is_daemon_running()

    click.echo(f"Platform: {sys.platform}")
    click.echo(f"Service manager: {manager}")

    if manager == "launchd":
        installed = launchd_is_installed()
        if installed:
            click.echo("Service: installed")
            svc_running, status_msg = launchd_status()
            if svc_running:
                click.secho(f"  Status: {status_msg} (via launchd)", fg="green")
            else:
                click.secho(f"  Status: {status_msg}", fg="yellow")
            click.echo(f"  Plist: {get_launchd_plist_path()}")
        else:
            click.echo("Service: not installed")
            if running:
                click.secho("  Daemon: running (standalone)", fg="green")
            else:
                click.secho("  Daemon: not running", fg="yellow")

    elif manager == "systemd":
        installed = systemd_is_installed()
        if installed:
            click.echo("Service: installed")
            svc_running, status_msg = systemd_status()
            if svc_running:
                click.secho(f"  Status: {status_msg} (via systemd)", fg="green")
            else:
                click.secho(f"  Status: {status_msg}", fg="yellow")
            click.echo(f"  Unit: {get_systemd_unit_path()}")
        else:
            click.echo("Service: not installed")
            if running:
                click.secho("  Daemon: running (standalone)", fg="green")
            else:
                click.secho("  Daemon: not running", fg="yellow")

    else:
        click.echo("Service: not available (no supported service manager)")
        if running:
            click.secho("  Daemon: running (standalone)", fg="green")
        else:
            click.secho("  Daemon: not running", fg="yellow")

    # Show mDNS status
    mdns_ok, mdns_msg = check_mdns_support()
    click.echo(f"\nmDNS: {mdns_msg}")
    if not mdns_ok:
        click.secho("  Device discovery may not work!", fg="yellow")

    # Show paths
    _, pid_file, log_file = get_daemon_paths()
    click.echo(f"\nLog: {log_file}")
    click.echo(f"PID file: {pid_file}")

"""CLI commands for Wormhole."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import click

from wormhole.control import (
    CloseSessionRequest,
    ErrorResponse,
    GetStatusRequest,
    ListSessionsRequest,
    OpenSessionRequest,
    send_control_request_sync,
)


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
def attach(session_name: str) -> None:
    """Attach to a session in terminal.

    Spawns an interactive claude --resume session in a screen.
    """
    from wormhole.control import SessionInfoResponse, SessionListResponse

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

    # Spawn claude --resume in a screen session
    screen_name = f"wormhole-{session_name}"

    # Check if screen session already exists
    result = subprocess.run(
        ["screen", "-list", screen_name],
        capture_output=True,
        text=True,
    )

    if screen_name in result.stdout:
        # Attach to existing screen
        click.echo(f"Attaching to existing screen session '{screen_name}'...")
        os.execvp("screen", ["screen", "-r", screen_name])
    else:
        # Create new screen with claude --resume
        click.echo(f"Creating screen session '{screen_name}'...")
        click.echo(f"Claude session ID: {claude_session_id}")
        os.execvp(
            "screen",
            [
                "screen",
                "-S",
                screen_name,
                "claude",
                "--resume",
                claude_session_id,
            ],
        )


@main.command()
@click.argument("session_name")
def close(session_name: str) -> None:
    """Close a session."""
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

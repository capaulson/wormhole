"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from wormhole.cli import generate_session_name, main
from wormhole.control import (
    ErrorResponse,
    SessionInfoResponse,
    SessionListResponse,
    StatusResponse,
    SuccessResponse,
)


class TestGenerateSessionName:
    """Tests for session name generation."""

    def test_uses_directory_name(self, tmp_path: Path) -> None:
        name = generate_session_name(tmp_path)
        assert tmp_path.name in name

    def test_includes_hash_suffix(self, tmp_path: Path) -> None:
        name = generate_session_name(tmp_path)
        # Format is name-hash
        parts = name.rsplit("-", 1)
        assert len(parts) == 2
        assert len(parts[1]) == 4  # 4 char hash


class TestCliVersion:
    """Tests for CLI version command."""

    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestStatusCommand:
    """Tests for status command."""

    def test_status_daemon_running(self) -> None:
        runner = CliRunner()

        with patch("wormhole.cli.send_control_request_sync") as mock:
            mock.return_value = StatusResponse(
                running=True,
                port=7117,
                machine_name="testbox",
                session_count=2,
                connected_clients=1,
            )

            result = runner.invoke(main, ["status"])

            assert result.exit_code == 0
            assert "running" in result.output
            assert "testbox" in result.output
            assert "7117" in result.output

    def test_status_daemon_not_running(self) -> None:
        runner = CliRunner()

        with patch("wormhole.cli.send_control_request_sync") as mock:
            mock.return_value = ErrorResponse(
                code="DAEMON_NOT_RUNNING",
                message="Daemon is not running",
            )

            result = runner.invoke(main, ["status"])

            assert result.exit_code == 1
            assert "not running" in result.output


class TestListCommand:
    """Tests for list command."""

    def test_list_no_sessions(self) -> None:
        runner = CliRunner()

        with (
            patch("wormhole.cli.ensure_daemon_running", return_value=True),
            patch("wormhole.cli.send_control_request_sync") as mock,
        ):
            mock.return_value = SessionListResponse(sessions=[])

            result = runner.invoke(main, ["list"])

            assert result.exit_code == 0
            assert "No active sessions" in result.output

    def test_list_with_sessions(self) -> None:
        runner = CliRunner()

        with (
            patch("wormhole.cli.ensure_daemon_running", return_value=True),
            patch("wormhole.cli.send_control_request_sync") as mock,
        ):
            mock.return_value = SessionListResponse(
                sessions=[
                    SessionInfoResponse(
                        name="test-session",
                        directory="/home/user/project",
                        state="working",
                        cost_usd=0.05,
                    ),
                ]
            )

            result = runner.invoke(main, ["list"])

            assert result.exit_code == 0
            assert "test-session" in result.output
            assert "working" in result.output
            assert "/home/user/project" in result.output


class TestOpenCommand:
    """Tests for open command."""

    def test_open_with_name(self) -> None:
        runner = CliRunner()

        with (
            patch("wormhole.cli.ensure_daemon_running", return_value=True),
            patch("wormhole.cli.send_control_request_sync") as mock,
        ):
            mock.return_value = SuccessResponse(message="Session created")

            result = runner.invoke(main, ["open", "--name", "my-session"])

            assert result.exit_code == 0
            assert "my-session" in result.output
            assert "created" in result.output

    def test_open_generates_name(self, tmp_path: Path) -> None:
        runner = CliRunner()

        with (
            patch("wormhole.cli.ensure_daemon_running", return_value=True),
            patch("wormhole.cli.send_control_request_sync") as mock,
        ):
            mock.return_value = SuccessResponse(message="Session created")

            with runner.isolated_filesystem(temp_dir=tmp_path):
                result = runner.invoke(main, ["open"])

                assert result.exit_code == 0
                assert "created" in result.output

    def test_open_duplicate_directory_error(self) -> None:
        runner = CliRunner()

        with (
            patch("wormhole.cli.ensure_daemon_running", return_value=True),
            patch("wormhole.cli.send_control_request_sync") as mock,
        ):
            mock.return_value = ErrorResponse(
                code="SESSION_EXISTS",
                message="A session already exists in this directory: test-session",
            )

            result = runner.invoke(main, ["open", "--name", "new-session"])

            assert result.exit_code == 1
            assert "already exists" in result.output


class TestCloseCommand:
    """Tests for close command."""

    def test_close_session(self) -> None:
        runner = CliRunner()

        with (
            patch("wormhole.cli.ensure_daemon_running", return_value=True),
            patch("wormhole.cli.send_control_request_sync") as mock,
        ):
            mock.return_value = SuccessResponse(message="Session closed")

            result = runner.invoke(main, ["close", "test-session"])

            assert result.exit_code == 0
            assert "closed" in result.output

    def test_close_nonexistent_session(self) -> None:
        runner = CliRunner()

        with (
            patch("wormhole.cli.ensure_daemon_running", return_value=True),
            patch("wormhole.cli.send_control_request_sync") as mock,
        ):
            mock.return_value = ErrorResponse(
                code="SESSION_NOT_FOUND",
                message="Session not found: nonexistent",
            )

            result = runner.invoke(main, ["close", "nonexistent"])

            assert result.exit_code == 1
            assert "not found" in result.output

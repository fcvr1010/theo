"""Tests for theo.cli."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from theo import __version__
from theo.cli import main


class TestCli:
    """Test CLI entry point."""

    def test_help_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--help"])
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "theo" in output
        assert "Usage" in output

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--version"])
        output = capsys.readouterr().out
        assert exit_code == 0
        assert __version__ in output

    def test_version_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["version"])
        assert exit_code == 0
        assert __version__ in capsys.readouterr().out

    def test_no_args_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main([])
        assert exit_code == 0
        assert "Usage" in capsys.readouterr().out

    def test_add_stub(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["add", "/some/path"])
        assert exit_code == 0
        assert "stub" in capsys.readouterr().out.lower()

    def test_add_missing_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["add"])
        assert exit_code == 1

    def test_remove_stub(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["remove", "/some/path"])
        assert exit_code == 0

    def test_remove_missing_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["remove"])
        assert exit_code == 1

    def test_list_stub(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["list"])
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "stub" in output.lower()
        assert "Monitored repositories" in output

    def test_stats_stub(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["stats"])
        assert exit_code == 0

    def test_stats_with_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["stats", "/some/path"])
        assert exit_code == 0

    def test_unknown_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["foobar"])
        assert exit_code == 1
        assert "unknown command" in capsys.readouterr().err.lower()


class TestDaemonCommand:
    """Test daemon CLI wiring."""

    def test_daemon_missing_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["daemon"])
        assert exit_code == 1
        assert "requires a subcommand" in capsys.readouterr().err

    def test_daemon_unknown_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["daemon", "restart"])
        assert exit_code == 1
        assert "unknown daemon subcommand" in capsys.readouterr().err

    @patch("theo.daemon.Daemon")
    @patch("theo.repo_manager.RepoManager")
    @patch("theo.config.TheoConfig")
    def test_daemon_start_calls_start(
        self,
        mock_config_cls: MagicMock,
        mock_manager_cls: MagicMock,
        mock_daemon_cls: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_daemon = mock_daemon_cls.return_value
        exit_code = main(["daemon", "start"])
        assert exit_code == 0
        mock_daemon.start.assert_called_once()
        assert "started" in capsys.readouterr().out.lower()

    @patch("theo.daemon.Daemon")
    @patch("theo.repo_manager.RepoManager")
    @patch("theo.config.TheoConfig")
    def test_daemon_start_already_running(
        self,
        mock_config_cls: MagicMock,
        mock_manager_cls: MagicMock,
        mock_daemon_cls: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from theo.daemon import DaemonError

        mock_daemon = mock_daemon_cls.return_value
        mock_daemon.start.side_effect = DaemonError("already running")
        exit_code = main(["daemon", "start"])
        assert exit_code == 1
        assert "already running" in capsys.readouterr().err

    @patch("theo.daemon.Daemon")
    @patch("theo.repo_manager.RepoManager")
    @patch("theo.config.TheoConfig")
    def test_daemon_stop_calls_stop(
        self,
        mock_config_cls: MagicMock,
        mock_manager_cls: MagicMock,
        mock_daemon_cls: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_daemon = mock_daemon_cls.return_value
        exit_code = main(["daemon", "stop"])
        assert exit_code == 0
        mock_daemon.stop.assert_called_once()
        assert "stopped" in capsys.readouterr().out.lower()

    @patch("theo.daemon.Daemon")
    @patch("theo.repo_manager.RepoManager")
    @patch("theo.config.TheoConfig")
    def test_daemon_stop_not_running(
        self,
        mock_config_cls: MagicMock,
        mock_manager_cls: MagicMock,
        mock_daemon_cls: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from theo.daemon import DaemonError

        mock_daemon = mock_daemon_cls.return_value
        mock_daemon.stop.side_effect = DaemonError("not running")
        exit_code = main(["daemon", "stop"])
        assert exit_code == 1
        assert "not running" in capsys.readouterr().err

    @patch("theo.daemon.Daemon")
    @patch("theo.repo_manager.RepoManager")
    @patch("theo.config.TheoConfig")
    def test_daemon_status_running(
        self,
        mock_config_cls: MagicMock,
        mock_manager_cls: MagicMock,
        mock_daemon_cls: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from theo.daemon import DaemonStatus

        mock_daemon = mock_daemon_cls.return_value
        mock_daemon.status.return_value = DaemonStatus(
            running=True, pid=12345, pid_file=Path("/tmp/test.pid"),
        )
        exit_code = main(["daemon", "status"])
        assert exit_code == 0
        output = capsys.readouterr().out
        assert "running" in output.lower()
        assert "12345" in output

    @patch("theo.daemon.Daemon")
    @patch("theo.repo_manager.RepoManager")
    @patch("theo.config.TheoConfig")
    def test_daemon_status_not_running(
        self,
        mock_config_cls: MagicMock,
        mock_manager_cls: MagicMock,
        mock_daemon_cls: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from theo.daemon import DaemonStatus

        mock_daemon = mock_daemon_cls.return_value
        mock_daemon.status.return_value = DaemonStatus(
            running=False, pid=None, pid_file=Path("/tmp/test.pid"),
        )
        exit_code = main(["daemon", "status"])
        assert exit_code == 0
        assert "not running" in capsys.readouterr().out.lower()

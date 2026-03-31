"""Tests for theo.cli."""

from __future__ import annotations

import io
import sys
from collections.abc import Generator
from unittest.mock import patch

import pytest

from theo import __version__
from theo.cli import main


@pytest.fixture()
def capture_stderr() -> Generator[io.StringIO, None, None]:
    """Capture stderr via a StringIO buffer."""
    buf = io.StringIO()
    with patch.object(sys, "stderr", buf):
        yield buf


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

    def test_stats_stub(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["stats"])
        assert exit_code == 0

    def test_stats_with_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["stats", "/some/path"])
        assert exit_code == 0

    def test_daemon_start(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["daemon", "start"])
        assert exit_code == 0

    def test_daemon_stop(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["daemon", "stop"])
        assert exit_code == 0

    def test_daemon_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["daemon", "status"])
        assert exit_code == 0

    def test_daemon_missing_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["daemon"])
        assert exit_code == 1

    def test_daemon_unknown_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["daemon", "restart"])
        assert exit_code == 1

    def test_unknown_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["foobar"])
        assert exit_code == 1
        assert "unknown command" in capsys.readouterr().err.lower()

"""Tests for theo.cli."""

from __future__ import annotations

from theo import __version__
from theo.cli import main


class TestCli:
    """Test CLI entry point."""

    def test_help_output(self, capsys: object) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["--help"])
        output = buf.getvalue()
        assert exit_code == 0
        assert "theo" in output
        assert "Usage" in output

    def test_version_flag(self, capsys: object) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["--version"])
        output = buf.getvalue()
        assert exit_code == 0
        assert __version__ in output

    def test_version_command(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["version"])
        assert exit_code == 0
        assert __version__ in buf.getvalue()

    def test_no_args_shows_help(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main([])
        assert exit_code == 0
        assert "Usage" in buf.getvalue()

    def test_add_stub(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["add", "/some/path"])
        assert exit_code == 0
        assert "stub" in buf.getvalue().lower()

    def test_add_missing_path(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            exit_code = main(["add"])
        assert exit_code == 1

    def test_remove_stub(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["remove", "/some/path"])
        assert exit_code == 0

    def test_remove_missing_path(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            exit_code = main(["remove"])
        assert exit_code == 1

    def test_stats_stub(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["stats"])
        assert exit_code == 0

    def test_stats_with_path(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["stats", "/some/path"])
        assert exit_code == 0

    def test_daemon_start(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["daemon", "start"])
        assert exit_code == 0

    def test_daemon_stop(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["daemon", "stop"])
        assert exit_code == 0

    def test_daemon_status(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            exit_code = main(["daemon", "status"])
        assert exit_code == 0

    def test_daemon_missing_subcommand(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            exit_code = main(["daemon"])
        assert exit_code == 1

    def test_daemon_unknown_subcommand(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            exit_code = main(["daemon", "restart"])
        assert exit_code == 1

    def test_unknown_command(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            exit_code = main(["foobar"])
        assert exit_code == 1
        assert "unknown command" in buf.getvalue().lower()

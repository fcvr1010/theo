"""Tests for theo.lens_runner."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from theo.cli_adapter import CLICommand
from theo.config import TheoConfig
from theo.lens_runner import (
    _MAX_CHANGED_FILES_IN_MESSAGE,
    LensRunner,
    LensRunResult,
    _build_message,
    make_lens_callback,
)
from theo.repo_manager import PullResult, RepoEntry

# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_entry(
    slug: str = "org-repo",
    clone_path: str = "/tmp/repos/org-repo",
    db_path: str = "/tmp/db/org-repo",
    enabled_lenses: list[str] | None = None,
) -> RepoEntry:
    return RepoEntry(
        url="https://github.com/org/repo.git",
        slug=slug,
        clone_path=clone_path,
        db_path=db_path,
        frequency_minutes=30,
        last_checked_revision=None,
        last_run_at=None,
        enabled_lenses=["architect"] if enabled_lenses is None else enabled_lenses,
        added_at="2025-01-01T00:00:00+00:00",
    )


@pytest.fixture()
def config(tmp_path: Path) -> TheoConfig:
    cfg = TheoConfig(base_dir=tmp_path / "theo-home", cli_command="echo")
    cfg.ensure_dirs()
    return cfg


@pytest.fixture()
def mock_repo_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.get.return_value = _make_entry()
    mgr.get_current_sha.return_value = "abc123def456"
    return mgr


# ── LensRunResult ─────────────────────────────────────────────────────────


class TestLensRunResult:
    def test_frozen(self) -> None:
        result = LensRunResult(success=True, exit_code=0, duration_seconds=1.5, error_message=None)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]

    def test_fields(self) -> None:
        result = LensRunResult(
            success=False, exit_code=1, duration_seconds=2.0, error_message="boom"
        )
        assert result.success is False
        assert result.exit_code == 1
        assert result.duration_seconds == 2.0
        assert result.error_message == "boom"


# ── _build_message ────────────────────────────────────────────────────────


class TestBuildMessage:
    def test_full_analysis(self) -> None:
        entry = _make_entry()
        msg = _build_message(entry, "abc123", None)
        assert "Repository: /tmp/repos/org-repo" in msg
        assert "Database: /tmp/db/org-repo" in msg
        assert "Current SHA: abc123" in msg
        assert "Mode: full analysis" in msg

    def test_incremental_with_files(self) -> None:
        entry = _make_entry()
        msg = _build_message(entry, "abc123", ["foo.py", "bar.py"])
        assert "Mode: incremental (2 changed files)" in msg
        assert "  - foo.py" in msg
        assert "  - bar.py" in msg

    def test_incremental_empty_list(self) -> None:
        entry = _make_entry()
        msg = _build_message(entry, "abc123", [])
        assert "Mode: incremental (0 changed files)" in msg

    def test_truncation(self) -> None:
        entry = _make_entry()
        files = [f"file_{i}.py" for i in range(_MAX_CHANGED_FILES_IN_MESSAGE + 50)]
        msg = _build_message(entry, "sha", files)
        assert "... and 50 more" in msg
        # Should contain the first N files, not all
        assert "  - file_0.py" in msg
        assert f"  - file_{_MAX_CHANGED_FILES_IN_MESSAGE - 1}.py" in msg
        assert f"  - file_{_MAX_CHANGED_FILES_IN_MESSAGE}.py" not in msg


# ── LensRunner.run ────────────────────────────────────────────────────────


class TestLensRunnerRun:
    @patch("theo.lens_runner.load_prompt", return_value="You are an architect lens.")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_successful_run(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(
            cmd=["echo", "--print", "msg"], temp_files=[]
        )
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.return_value = (b"output text", b"")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc

        result = runner.run("org-repo", "architect")

        assert result.success is True
        assert result.exit_code == 0
        assert result.duration_seconds >= 0
        assert result.error_message is None

        # Adapter was called with prompt and message.
        mock_adapter.build_command.assert_called_once()
        call_args = mock_adapter.build_command.call_args
        assert call_args[0][0] == "You are an architect lens."  # system_prompt
        assert "org-repo" in call_args[0][1] or "/tmp/repos/org-repo" in call_args[0][1]

    @patch("theo.lens_runner.load_prompt", return_value="prompt")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_nonzero_exit_code(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(cmd=["echo", "msg"], temp_files=[])
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.return_value = (b"", b"some error output")
        proc.returncode = 1
        proc.pid = 12345
        mock_popen.return_value = proc

        result = runner.run("org-repo", "architect")

        assert result.success is False
        assert result.exit_code == 1
        assert result.error_message is not None
        assert "some error output" in result.error_message

    @patch("theo.lens_runner.load_prompt", return_value="prompt")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_timeout_returns_failure(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(cmd=["echo", "msg"], temp_files=[])
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="echo", timeout=600)
        proc.pid = 12345
        proc.wait.return_value = None
        mock_popen.return_value = proc

        result = runner.run("org-repo", "architect", changed_files=["a.py"])

        assert result.success is False
        assert result.exit_code == -1
        assert result.error_message is not None
        assert "Timed out" in result.error_message

    @patch("theo.lens_runner.load_prompt", return_value="prompt")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_timeout_full_vs_incremental(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        """Full analysis uses 1800s timeout, incremental uses 600s."""
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(cmd=["echo", "msg"], temp_files=[])
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc

        # Full analysis
        runner.run("org-repo", "architect", changed_files=None)
        call_timeout = proc.communicate.call_args[1].get("timeout")
        assert call_timeout == 1800

        # Incremental
        runner.run("org-repo", "architect", changed_files=["x.py"])
        call_timeout = proc.communicate.call_args[1].get("timeout")
        assert call_timeout == 600

    @patch("theo.lens_runner.load_prompt", return_value="prompt")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_start_new_session(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(cmd=["echo", "msg"], temp_files=[])
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc

        runner.run("org-repo", "architect")

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["start_new_session"] is True

    @patch("theo.lens_runner.load_prompt", return_value="prompt")
    @patch("theo.lens_runner.subprocess.Popen", side_effect=FileNotFoundError("not found"))
    def test_cli_not_found(
        self,
        _mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(cmd=["echo", "msg"], temp_files=[])
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        result = runner.run("org-repo", "architect")

        assert result.success is False
        assert result.exit_code == -1
        assert "not found" in (result.error_message or "")

    @patch("theo.lens_runner.load_prompt", return_value="the prompt text")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_temp_files_cleaned_up(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        """Temp files returned by the adapter are cleaned up after execution."""
        import tempfile

        fd, tmp_path = tempfile.mkstemp(suffix=".md")
        os.close(fd)

        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(
            cmd=["echo", "msg"], temp_files=[tmp_path]
        )
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc

        runner.run("org-repo", "architect")

        # Temp file should have been cleaned up.
        assert not os.path.exists(tmp_path)

    @patch("theo.lens_runner.load_prompt", return_value="prompt")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_adapter_receives_message_with_repo_info(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(cmd=["echo", "msg"], temp_files=[])
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        proc.pid = 12345
        mock_popen.return_value = proc

        runner.run("org-repo", "architect", changed_files=["main.py"])

        call_args = mock_adapter.build_command.call_args
        message = call_args[0][1]
        assert "/tmp/repos/org-repo" in message
        assert "/tmp/db/org-repo" in message
        assert "abc123def456" in message
        assert "main.py" in message

    @patch("theo.lens_runner.load_prompt", return_value="prompt")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_nonzero_exit_no_stderr(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        """Non-zero exit with empty stderr produces a fallback error message."""
        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(cmd=["echo", "msg"], temp_files=[])
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        proc = MagicMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 2
        proc.pid = 12345
        mock_popen.return_value = proc

        result = runner.run("org-repo", "architect")

        assert result.success is False
        assert result.exit_code == 2
        assert result.error_message == "CLI exited with code 2"

    def test_default_adapter_from_config(
        self,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        """When no adapter is provided, one is resolved from config.cli_command."""
        # config.cli_command is "echo" which is not a supported adapter.
        # Override to "claude" to test the auto-resolution path.
        cfg = TheoConfig(base_dir=config.base_dir, cli_command="claude")
        runner = LensRunner(cfg, mock_repo_manager)
        # Should have created a ClaudeCodeAdapter.
        from theo.cli_adapter import ClaudeCodeAdapter

        assert isinstance(runner._cli_adapter, ClaudeCodeAdapter)

    @patch("theo.lens_runner.load_prompt", return_value="prompt text")
    @patch("theo.lens_runner.subprocess.Popen")
    def test_temp_files_cleaned_up_on_error(
        self,
        mock_popen: MagicMock,
        _mock_load: MagicMock,
        config: TheoConfig,
        mock_repo_manager: MagicMock,
    ) -> None:
        """Temp files are cleaned up even when _exec raises."""
        import tempfile

        fd, tmp_path = tempfile.mkstemp(suffix=".md")
        os.close(fd)

        mock_adapter = MagicMock()
        mock_adapter.build_command.return_value = CLICommand(
            cmd=["echo", "msg"], temp_files=[tmp_path]
        )
        runner = LensRunner(config, mock_repo_manager, cli_adapter=mock_adapter)

        mock_popen.side_effect = FileNotFoundError("boom")

        runner.run("org-repo", "architect")

        assert not os.path.exists(tmp_path)


# ── make_lens_callback ────────────────────────────────────────────────────


class TestMakeLensCallback:
    def test_calls_run_for_each_lens(self) -> None:
        mock_runner = MagicMock(spec=LensRunner)
        callback = make_lens_callback(mock_runner)

        entry = _make_entry(enabled_lenses=["architect", "security"])
        pull = PullResult(
            sha_before="aaa",
            sha_after="bbb",
            changed_files=["x.py", "y.py"],
        )

        callback(entry, pull)

        assert mock_runner.run.call_count == 2
        mock_runner.run.assert_any_call("org-repo", "architect", changed_files=["x.py", "y.py"])
        mock_runner.run.assert_any_call("org-repo", "security", changed_files=["x.py", "y.py"])

    def test_empty_changed_files_becomes_none(self) -> None:
        """Empty changed_files list is converted to None (full analysis)."""
        mock_runner = MagicMock(spec=LensRunner)
        callback = make_lens_callback(mock_runner)

        entry = _make_entry(enabled_lenses=["architect"])
        pull = PullResult(sha_before="aaa", sha_after="aaa", changed_files=[])

        callback(entry, pull)

        mock_runner.run.assert_called_once_with("org-repo", "architect", changed_files=None)

    def test_no_enabled_lenses(self) -> None:
        mock_runner = MagicMock(spec=LensRunner)
        callback = make_lens_callback(mock_runner)

        entry = _make_entry(enabled_lenses=[])
        pull = PullResult(sha_before="aaa", sha_after="bbb", changed_files=["z.py"])

        callback(entry, pull)

        mock_runner.run.assert_not_called()

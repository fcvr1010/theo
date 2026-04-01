"""Tests for theo.daemon."""

from __future__ import annotations

import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from theo.config import TheoConfig
from theo.daemon import Daemon, DaemonError, DaemonStatus
from theo.repo_manager import PullResult, RepoEntry


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def config(tmp_path: Path) -> TheoConfig:
    """Create a TheoConfig with a temp base_dir."""
    cfg = TheoConfig(base_dir=tmp_path / "theo-home")
    cfg.ensure_dirs()
    return cfg


@pytest.fixture()
def manager() -> MagicMock:
    """Create a mock RepoManager."""
    return MagicMock()


@pytest.fixture()
def daemon(config: TheoConfig, manager: MagicMock) -> Daemon:
    """Create a Daemon with a temp config and mock manager."""
    return Daemon(config, manager)


def _make_entry(
    slug: str = "test-repo",
    frequency_minutes: int = 30,
    last_run_at: str | None = None,
    last_checked_revision: str | None = None,
) -> RepoEntry:
    """Create a RepoEntry for testing."""
    return RepoEntry(
        url=f"https://github.com/org/{slug}.git",
        slug=slug,
        clone_path=f"/tmp/repos/{slug}",
        db_path=f"/tmp/db/{slug}",
        frequency_minutes=frequency_minutes,
        last_checked_revision=last_checked_revision,
        last_run_at=last_run_at,
        enabled_lenses=[],
        added_at="2025-01-01T00:00:00+00:00",
    )


def _make_pull_result(
    changed: bool = False,
) -> PullResult:
    """Create a PullResult for testing."""
    if changed:
        return PullResult(sha_before="aaa", sha_after="bbb", changed_files=["file.py"])
    return PullResult(sha_before="aaa", sha_after="aaa", changed_files=[])


# ── DaemonStatus dataclass ───────────────────────────────────────────────


class TestDaemonStatus:
    """Test the DaemonStatus dataclass."""

    def test_fields(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "daemon.pid"
        status = DaemonStatus(running=True, pid=42, pid_file=pid_file)
        assert status.running is True
        assert status.pid == 42
        assert status.pid_file == pid_file

    def test_not_running(self, tmp_path: Path) -> None:
        status = DaemonStatus(running=False, pid=None, pid_file=tmp_path / "daemon.pid")
        assert status.running is False
        assert status.pid is None


# ── DaemonError ──────────────────────────────────────────────────────────


class TestDaemonError:
    """Test DaemonError is a standalone exception."""

    def test_not_subclass_of_base_exception_types(self) -> None:
        # DaemonError should NOT be a subclass of RepoManagerError.
        from theo.repo_manager import RepoManagerError

        assert not issubclass(DaemonError, RepoManagerError)

    def test_is_exception(self) -> None:
        assert issubclass(DaemonError, Exception)

    def test_message(self) -> None:
        err = DaemonError("test message")
        assert str(err) == "test message"


# ── pid_file property ────────────────────────────────────────────────────


class TestPidFile:
    """Test the pid_file property."""

    def test_pid_file_path(self, daemon: Daemon, config: TheoConfig) -> None:
        assert daemon.pid_file == config.base_dir / "daemon.pid"


# ── status() ─────────────────────────────────────────────────────────────


class TestStatus:
    """Test the status() method."""

    def test_no_pid_file(self, daemon: Daemon) -> None:
        st = daemon.status()
        assert st.running is False
        assert st.pid is None
        assert st.pid_file == daemon.pid_file

    def test_valid_pid_file_process_alive(self, daemon: Daemon) -> None:
        daemon.pid_file.write_text("12345")
        with patch("theo.daemon.os.kill") as mock_kill:
            mock_kill.return_value = None  # no exception = process alive
            st = daemon.status()
        assert st.running is True
        assert st.pid == 12345
        mock_kill.assert_called_once_with(12345, 0)

    def test_stale_pid_file(self, daemon: Daemon) -> None:
        daemon.pid_file.write_text("99999")
        with patch("theo.daemon.os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError
            st = daemon.status()
        assert st.running is False
        assert st.pid is None
        # Stale PID file should be cleaned up.
        assert not daemon.pid_file.exists()

    def test_corrupt_pid_file(self, daemon: Daemon) -> None:
        daemon.pid_file.write_text("not-a-number")
        st = daemon.status()
        assert st.running is False
        assert st.pid is None
        assert not daemon.pid_file.exists()

    def test_permission_error_treated_as_running(self, daemon: Daemon) -> None:
        daemon.pid_file.write_text("12345")
        with patch("theo.daemon.os.kill") as mock_kill:
            mock_kill.side_effect = PermissionError
            st = daemon.status()
        assert st.running is True
        assert st.pid == 12345


# ── start() ──────────────────────────────────────────────────────────────


class TestStart:
    """Test the start() method."""

    def test_start_when_already_running(self, daemon: Daemon) -> None:
        daemon.pid_file.write_text("12345")
        with patch("theo.daemon.os.kill"):  # process alive
            with pytest.raises(DaemonError, match="already running"):
                daemon.start()

    @patch("theo.daemon.os.fork")
    def test_start_parent_returns(self, mock_fork: MagicMock, daemon: Daemon) -> None:
        """The parent process (first fork returns >0) should return immediately."""
        mock_fork.return_value = 42  # parent gets child PID
        daemon.start()
        mock_fork.assert_called_once()


# ── stop() ───────────────────────────────────────────────────────────────


class TestStop:
    """Test the stop() method."""

    def test_stop_when_not_running(self, daemon: Daemon) -> None:
        with pytest.raises(DaemonError, match="not running"):
            daemon.stop()

    def test_stop_sends_sigterm(self, daemon: Daemon) -> None:
        daemon.pid_file.write_text("12345")
        with patch("theo.daemon.os.kill") as mock_kill:
            # First call: status check (signal 0) -> alive.
            # Second call: SIGTERM -> ok.
            # Third call: status check (signal 0) -> dead (ProcessLookupError).
            mock_kill.side_effect = [
                None,  # status() os.kill(pid, 0) -> alive
                None,  # os.kill(pid, SIGTERM) -> ok
                ProcessLookupError,  # wait loop os.kill(pid, 0) -> dead
            ]
            daemon.stop()

        calls = mock_kill.call_args_list
        assert calls[0] == call(12345, 0)
        assert calls[1] == call(12345, signal.SIGTERM)
        assert calls[2] == call(12345, 0)
        # PID file should be removed.
        assert not daemon.pid_file.exists()

    def test_stop_already_dead_after_sigterm(self, daemon: Daemon) -> None:
        daemon.pid_file.write_text("12345")
        with patch("theo.daemon.os.kill") as mock_kill:
            mock_kill.side_effect = [
                None,  # status check -> alive
                ProcessLookupError,  # SIGTERM -> already dead
            ]
            daemon.stop()
        assert not daemon.pid_file.exists()

    @patch("theo.daemon.time.sleep")
    def test_stop_escalates_to_sigkill(self, mock_sleep: MagicMock, daemon: Daemon) -> None:
        daemon.pid_file.write_text("12345")

        alive_count = 0

        def fake_kill(pid: int, sig: int) -> None:
            nonlocal alive_count
            if sig == 0:
                alive_count += 1
                # Always alive during the wait loop -- force timeout.
                return
            if sig == signal.SIGKILL:
                return
            # SIGTERM -- do nothing (process ignores it).

        with patch("theo.daemon.os.kill", side_effect=fake_kill):
            with patch("theo.daemon.time.monotonic") as mock_mono:
                # Simulate: start at 0, then always past deadline.
                mock_mono.side_effect = [0.0, 11.0]
                daemon.stop()

        assert not daemon.pid_file.exists()


# ── tick() ───────────────────────────────────────────────────────────────


class TestTick:
    """Test the tick() method."""

    def test_repo_due_gets_pulled(self, daemon: Daemon, manager: MagicMock) -> None:
        """A repo with no last_run_at should be pulled (always due)."""
        entry = _make_entry(last_run_at=None)
        manager.list.return_value = [entry]
        manager.pull.return_value = _make_pull_result(changed=False)

        daemon.tick()

        manager.pull.assert_called_once_with("test-repo")
        manager.update.assert_called_once()
        update_kwargs = manager.update.call_args
        assert update_kwargs[0][0] == "test-repo"
        assert "last_run_at" in update_kwargs[1]

    def test_repo_not_due_is_skipped(self, daemon: Daemon, manager: MagicMock) -> None:
        """A repo whose last_run_at is recent should be skipped."""
        recent = datetime.now(UTC).isoformat()
        entry = _make_entry(last_run_at=recent, frequency_minutes=30)
        manager.list.return_value = [entry]

        daemon.tick()

        manager.pull.assert_not_called()
        manager.update.assert_not_called()

    def test_repo_due_by_elapsed_time(self, daemon: Daemon, manager: MagicMock) -> None:
        """A repo whose last_run_at is older than frequency_minutes should be pulled."""
        old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
        entry = _make_entry(last_run_at=old_time, frequency_minutes=30)
        manager.list.return_value = [entry]
        manager.pull.return_value = _make_pull_result(changed=False)

        daemon.tick()

        manager.pull.assert_called_once_with("test-repo")

    def test_lens_callback_invoked_on_changes(
        self, config: TheoConfig, manager: MagicMock
    ) -> None:
        """When changes are detected, the lens callback should be invoked."""
        callback = MagicMock()
        d = Daemon(config, manager, lens_callback=callback)

        entry = _make_entry(last_run_at=None)
        result = _make_pull_result(changed=True)
        manager.list.return_value = [entry]
        manager.pull.return_value = result

        d.tick()

        callback.assert_called_once_with(entry, result)

    def test_lens_callback_not_invoked_without_changes(
        self, config: TheoConfig, manager: MagicMock
    ) -> None:
        """When no changes are detected, the lens callback should not be invoked."""
        callback = MagicMock()
        d = Daemon(config, manager, lens_callback=callback)

        entry = _make_entry(last_run_at=None)
        manager.list.return_value = [entry]
        manager.pull.return_value = _make_pull_result(changed=False)

        d.tick()

        callback.assert_not_called()

    def test_no_callback_pull_only_mode(self, daemon: Daemon, manager: MagicMock) -> None:
        """With no lens_callback, daemon runs in pull-only mode without errors."""
        entry = _make_entry(last_run_at=None)
        manager.list.return_value = [entry]
        manager.pull.return_value = _make_pull_result(changed=True)

        daemon.tick()  # Should not raise.

        manager.pull.assert_called_once()
        manager.update.assert_called_once()

    def test_error_isolation_between_repos(
        self, daemon: Daemon, manager: MagicMock
    ) -> None:
        """A failure in one repo should not prevent processing of others."""
        entry_a = _make_entry(slug="repo-a", last_run_at=None)
        entry_b = _make_entry(slug="repo-b", last_run_at=None)
        manager.list.return_value = [entry_a, entry_b]

        # repo-a fails, repo-b succeeds.
        manager.pull.side_effect = [
            RuntimeError("network error"),
            _make_pull_result(changed=False),
        ]

        daemon.tick()  # Should not raise.

        assert manager.pull.call_count == 2
        # update should only be called for repo-b.
        manager.update.assert_called_once()
        assert manager.update.call_args[0][0] == "repo-b"

    def test_last_checked_revision_updated_on_changes(
        self, daemon: Daemon, manager: MagicMock
    ) -> None:
        """When changes are detected, last_checked_revision should be updated."""
        entry = _make_entry(last_run_at=None)
        manager.list.return_value = [entry]
        manager.pull.return_value = PullResult(
            sha_before="aaa", sha_after="bbb", changed_files=["x.py"]
        )

        daemon.tick()

        update_kwargs = manager.update.call_args[1]
        assert update_kwargs["last_checked_revision"] == "bbb"

    def test_last_checked_revision_not_updated_without_changes(
        self, daemon: Daemon, manager: MagicMock
    ) -> None:
        """When no changes, last_checked_revision should not be in the update."""
        entry = _make_entry(last_run_at=None)
        manager.list.return_value = [entry]
        manager.pull.return_value = _make_pull_result(changed=False)

        daemon.tick()

        update_kwargs = manager.update.call_args[1]
        assert "last_checked_revision" not in update_kwargs

    def test_empty_repo_list(self, daemon: Daemon, manager: MagicMock) -> None:
        """Tick with no repos should complete without error."""
        manager.list.return_value = []
        daemon.tick()
        manager.pull.assert_not_called()


# ── run() ────────────────────────────────────────────────────────────────


class TestRun:
    """Test the run() event loop."""

    @patch("theo.daemon.time.sleep")
    def test_signal_handler_sets_shutdown(self, mock_sleep: MagicMock, daemon: Daemon) -> None:
        """Verify that the signal handler sets _shutdown, causing run() to exit."""
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)
        try:
            # Make tick set _shutdown on first call so run() exits.
            def stop_on_tick() -> None:
                daemon._shutdown = True

            with patch.object(daemon, "tick", side_effect=stop_on_tick):
                daemon.run()

            assert daemon._shutdown is True
        finally:
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)

    @patch("theo.daemon.time.sleep")
    def test_run_calls_tick(self, mock_sleep: MagicMock, daemon: Daemon) -> None:
        """Verify that run() calls tick()."""
        call_count = 0

        def count_and_stop() -> None:
            nonlocal call_count
            call_count += 1
            daemon._shutdown = True

        with patch.object(daemon, "tick", side_effect=count_and_stop):
            daemon.run()

        assert call_count == 1

    @patch("theo.daemon.time.sleep")
    def test_run_installs_signal_handlers(
        self, mock_sleep: MagicMock, daemon: Daemon
    ) -> None:
        """Verify that run() installs signal handlers for SIGTERM and SIGINT."""
        handlers_during_run: dict[int, object] = {}

        def capture_handlers() -> None:
            handlers_during_run[signal.SIGTERM] = signal.getsignal(signal.SIGTERM)
            handlers_during_run[signal.SIGINT] = signal.getsignal(signal.SIGINT)
            daemon._shutdown = True

        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)
        try:
            with patch.object(daemon, "tick", side_effect=capture_handlers):
                daemon.run()

            # The handlers should be callables (not SIG_DFL or SIG_IGN).
            assert callable(handlers_during_run[signal.SIGTERM])
            assert callable(handlers_during_run[signal.SIGINT])
        finally:
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)

    @patch("theo.daemon.time.sleep")
    def test_run_survives_tick_exception(
        self, mock_sleep: MagicMock, daemon: Daemon
    ) -> None:
        """If tick() raises, run() should continue to the next iteration."""
        call_count = 0

        def fail_then_stop() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("tick failed")
            daemon._shutdown = True

        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)
        try:
            with patch.object(daemon, "tick", side_effect=fail_then_stop):
                daemon.run()

            assert call_count == 2
        finally:
            signal.signal(signal.SIGTERM, original_sigterm)
            signal.signal(signal.SIGINT, original_sigint)

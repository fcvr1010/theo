"""Background daemon for periodic repository polling.

    Daemon(config, repo_manager, lens_callback=None)

Manages the lifecycle of a background process that periodically pulls
tracked repositories and optionally invokes a lens callback when changes
are detected.

Process lifecycle:
- ``start()``          -- double-fork daemonization, writes PID file.
- ``run_foreground()`` -- foreground mode with PID file lifecycle.
- ``stop()``           -- sends SIGTERM (then SIGKILL after 10s), removes PID file.
- ``status()``         -- reads PID file, checks process liveness.
- ``run()``            -- foreground event loop (called by the daemonized child).
- ``tick()``           -- single iteration: check each repo, pull if due, invoke callback.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from theo import get_logger
from theo.config import TheoConfig
from theo.repo_manager import PullResult, RepoEntry, RepoManager

_log = get_logger("daemon")

_STOP_TIMEOUT = 10  # seconds to wait after SIGTERM before SIGKILL


class DaemonError(Exception):
    """Raised for daemon lifecycle errors (start/stop failures)."""


@dataclass
class DaemonStatus:
    """Snapshot of the daemon's current state."""

    running: bool
    pid: int | None
    pid_file: Path


class Daemon:
    """Background polling daemon.

    Args:
        config: Theo configuration (provides ``base_dir`` for PID file).
        repo_manager: Used to list, pull, and update tracked repositories.
        lens_callback: Optional callback invoked when a pull detects changes.
            Signature: ``(entry, pull_result) -> None``.  If *None*, the daemon
            runs in pull-only mode (no lens invocation).
        tick_interval: Seconds between ticks (default 60).
    """

    def __init__(
        self,
        config: TheoConfig,
        repo_manager: RepoManager,
        lens_callback: Callable[[RepoEntry, PullResult], None] | None = None,
        tick_interval: int = 60,
    ) -> None:
        self._config = config
        self._repo_manager = repo_manager
        self._lens_callback = lens_callback
        self._tick_interval = tick_interval
        self._shutdown = False

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def pid_file(self) -> Path:
        """Path to the daemon PID file."""
        return self._config.base_dir / "daemon.pid"

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the daemon via double-fork.

        Raises:
            DaemonError: If the daemon is already running.
        """
        current = self.status()
        if current.running:
            raise DaemonError(f"Daemon is already running (pid={current.pid})")

        _log.info("Starting daemon (double-fork)")

        # First fork.
        pid = os.fork()
        if pid > 0:
            # Parent -- wait briefly for child to set up, then return.
            return

        # Child -- become session leader.
        os.setsid()

        # Second fork.
        pid = os.fork()
        if pid > 0:
            # Intermediate child exits immediately.
            os._exit(0)

        # Grandchild -- the actual daemon process.
        self._run_as_daemon()

    def run_foreground(self) -> None:
        """Run the daemon in the foreground with PID file lifecycle.

        Writes the PID file, calls :meth:`run`, and cleans up the PID file
        on exit.  Intended for ``theo daemon start --foreground``.
        """
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()))
        _log.info("Daemon running in foreground (pid=%d)", os.getpid())
        try:
            self.run()
        finally:
            self._remove_pid_file()

    def _run_as_daemon(self) -> None:
        """Grandchild process logic: redirect stdio, write PID, run, clean up."""
        # Redirect stdin/stdout/stderr to /dev/null.
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, sys.stdin.fileno())
        os.dup2(devnull, sys.stdout.fileno())
        os.dup2(devnull, sys.stderr.fileno())
        os.close(devnull)

        # Write PID file.
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()))

        _log.info("Daemon started (pid=%d)", os.getpid())

        try:
            self.run()
        finally:
            # Clean up PID file on exit.
            self._remove_pid_file()
            os._exit(0)

    def stop(self) -> None:
        """Stop the running daemon.

        Sends SIGTERM, waits up to 10 seconds, then SIGKILL if still alive.
        Removes the PID file afterward.

        Raises:
            DaemonError: If the daemon is not running.
        """
        current = self.status()
        if not current.running:
            raise DaemonError("Daemon is not running")

        pid = current.pid
        assert pid is not None  # guaranteed by running=True

        _log.info("Stopping daemon (pid=%d)", pid)

        # Send SIGTERM.
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            # Already dead -- clean up PID file and return.
            _log.warning("Daemon pid=%d already dead, cleaning up PID file", pid)
            self._remove_pid_file()
            return

        # Wait for process to exit.
        deadline = time.monotonic() + _STOP_TIMEOUT
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                # Process exited cleanly.
                _log.info("Daemon pid=%d stopped", pid)
                self._remove_pid_file()
                return
            time.sleep(0.2)

        # Still alive after timeout -- escalate to SIGKILL.
        _log.warning("Daemon pid=%d did not stop after %ds, sending SIGKILL", pid, _STOP_TIMEOUT)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)

        self._remove_pid_file()
        _log.info("Daemon pid=%d killed", pid)

    def status(self) -> DaemonStatus:
        """Check the current daemon status.

        Returns:
            A ``DaemonStatus`` with ``running``, ``pid``, and ``pid_file``.
            If the PID file references a dead process (stale), it is removed
            and ``running=False`` is returned.
        """
        if not self.pid_file.exists():
            return DaemonStatus(running=False, pid=None, pid_file=self.pid_file)

        try:
            pid_text = self.pid_file.read_text().strip()
            pid = int(pid_text)
        except (ValueError, OSError):
            # Corrupt or unreadable PID file -- treat as not running.
            self._remove_pid_file()
            return DaemonStatus(running=False, pid=None, pid_file=self.pid_file)

        # Check if process is alive.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Stale PID file -- process is dead.
            _log.warning("Stale PID file (pid=%d), removing", pid)
            self._remove_pid_file()
            return DaemonStatus(running=False, pid=None, pid_file=self.pid_file)
        except PermissionError:
            # Process exists but we can't signal it -- treat as running.
            return DaemonStatus(running=True, pid=pid, pid_file=self.pid_file)

        return DaemonStatus(running=True, pid=pid, pid_file=self.pid_file)

    def tick(self) -> None:
        """Single polling iteration.

        For each tracked repository, check if enough time has elapsed since
        ``last_run_at`` based on ``frequency_minutes``.  If due: pull, invoke
        lens callback on changes, and update the repo entry.

        Each repository is processed in its own try/except so a failure in
        one does not affect the others.
        """
        entries = self._repo_manager.list()
        now = datetime.now(UTC)

        for entry in entries:
            try:
                self._tick_repo(entry, now)
            except Exception:
                _log.exception("Error processing repo %s", entry.slug)

    def run(self) -> None:
        """Foreground event loop.

        Installs signal handlers for SIGTERM/SIGINT, then loops: ``tick()``
        followed by a 60-second sleep, until ``self._shutdown`` is set.
        """
        self._shutdown = False

        def _handle_signal(signum: int, frame: object) -> None:
            _log.info("Received signal %d, shutting down", signum)
            self._shutdown = True

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        _log.info("Daemon run loop starting")

        while not self._shutdown:
            try:
                self.tick()
            except Exception:
                _log.exception("Unexpected error in tick")

            # Sleep in small increments so we can respond to shutdown quickly.
            for _ in range(self._tick_interval):
                if self._shutdown:
                    break
                time.sleep(1)

        _log.info("Daemon run loop exited")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _tick_repo(self, entry: RepoEntry, now: datetime) -> None:
        """Process a single repository during a tick."""
        if not self._is_due(entry, now):
            _log.debug("Skipping %s (not due)", entry.slug)
            return

        _log.info("Pulling %s", entry.slug)
        result = self._repo_manager.pull(entry.slug)

        has_changes = result.sha_before != result.sha_after

        if has_changes and self._lens_callback is not None:
            _log.info("Changes detected in %s, invoking lens callback", entry.slug)
            self._lens_callback(entry, result)

        # Update tracking state.
        update_fields: dict[str, str] = {
            "last_run_at": now.isoformat(),
        }
        if has_changes:
            update_fields["last_checked_revision"] = result.sha_after

        self._repo_manager.update(entry.slug, **update_fields)

    @staticmethod
    def _is_due(entry: RepoEntry, now: datetime) -> bool:
        """Return True if the repo is due for a pull."""
        if entry.last_run_at is None:
            return True

        last_run = datetime.fromisoformat(entry.last_run_at)
        elapsed_minutes = (now - last_run).total_seconds() / 60
        return elapsed_minutes >= entry.frequency_minutes

    def _remove_pid_file(self) -> None:
        """Remove the PID file if it exists."""
        try:
            self.pid_file.unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("Failed to remove PID file: %s", exc)

"""Run a lens analysis against a repository via the configured CLI.

    LensRunner(config, repo_manager) -- orchestrates CLI subprocess invocation.
    LensRunResult(success, exit_code, duration_seconds, error_message) -- outcome.
    make_lens_callback(runner) -- factory for daemon-compatible callback.

Given a repo slug and lens name, LensRunner loads the lens prompt, builds the
initial message (repo path, DB path, current SHA, changed files), and invokes
the CLI as a subprocess with a configurable timeout.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from theo import get_logger
from theo.cli_adapter import CLIAdapter, adapter_for_config
from theo.config import TheoConfig
from theo.lenses import load_prompt
from theo.repo_manager import PullResult, RepoEntry, RepoManager

_log = get_logger("lens_runner")

# Timeout defaults in seconds.
_TIMEOUT_FULL = 1800  # 30 minutes for full analysis
_TIMEOUT_INCREMENTAL = 600  # 10 minutes for incremental analysis

# Truncate changed-files list beyond this count to keep the message size manageable.
_MAX_CHANGED_FILES_IN_MESSAGE = 500


@dataclass(frozen=True)
class LensRunResult:
    """Outcome of a single lens invocation."""

    success: bool
    exit_code: int
    duration_seconds: float
    error_message: str | None


class LensRunner:
    """Bridge between the daemon/scheduler and the agentic CLI.

    Args:
        config: Theo runtime configuration.
        repo_manager: Provides repo lookup and git SHA queries (read-only).
    """

    def __init__(
        self,
        config: TheoConfig,
        repo_manager: RepoManager,
        cli_adapter: CLIAdapter | None = None,
    ) -> None:
        self._config = config
        self._repo_manager = repo_manager
        self._cli_adapter = cli_adapter or adapter_for_config(config.cli_command)

    def run(
        self,
        repo_slug: str,
        lens_name: str,
        changed_files: list[str] | None = None,
    ) -> LensRunResult:
        """Invoke a lens analysis against a repository.

        Args:
            repo_slug: Slug of the tracked repository.
            lens_name: Lens identifier (e.g. ``"architect"``).
            changed_files: Files that changed since the last run.  ``None``
                triggers a full analysis; an explicit list triggers incremental.

        Returns:
            ``LensRunResult`` with exit code, timing, and any error message.
        """
        _log.info(
            "Starting lens %r on repo %r (mode=%s)",
            lens_name,
            repo_slug,
            "incremental" if changed_files is not None else "full",
        )

        # -- Gather inputs ------------------------------------------------
        entry = self._repo_manager.get(repo_slug)
        sha = self._repo_manager.get_current_sha(repo_slug)
        prompt_text = load_prompt(lens_name)
        message = _build_message(entry, sha, changed_files)
        timeout = _TIMEOUT_INCREMENTAL if changed_files is not None else _TIMEOUT_FULL

        # -- Build CLI command via adapter -----------------------------------
        cli_command = self._cli_adapter.build_command(prompt_text, message)
        try:
            return self._exec(cli_command.cmd, timeout)
        finally:
            for tmp_path in cli_command.temp_files:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

    # -- Private helpers --------------------------------------------------

    def _exec(self, cmd: list[str], timeout: int) -> LensRunResult:
        """Run the CLI subprocess and return the result."""
        t0 = time.monotonic()

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            duration = time.monotonic() - t0
            msg = f"CLI command not found: {exc}"
            _log.error(msg)
            return LensRunResult(
                success=False,
                exit_code=-1,
                duration_seconds=duration,
                error_message=msg,
            )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the entire process group to clean up child processes.
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()

            duration = time.monotonic() - t0
            msg = f"Timed out after {timeout}s"
            _log.error("Lens run timed out: %s", msg)
            return LensRunResult(
                success=False,
                exit_code=-1,
                duration_seconds=duration,
                error_message=msg,
            )

        duration = time.monotonic() - t0

        _log.debug("stdout: %s", stdout.decode(errors="replace")[:2000])
        _log.debug("stderr: %s", stderr.decode(errors="replace")[:2000])

        if proc.returncode != 0:
            err_text = stderr.decode(errors="replace").strip()[:500]
            err_msg = (
                f"CLI exited with code {proc.returncode}: {err_text}"
                if err_text
                else f"CLI exited with code {proc.returncode}"
            )
            _log.warning(
                "Lens run failed (exit_code=%d, duration=%.1fs)",
                proc.returncode,
                duration,
            )
            return LensRunResult(
                success=False,
                exit_code=proc.returncode,
                duration_seconds=duration,
                error_message=err_msg,
            )

        _log.info("Lens run completed successfully (duration=%.1fs)", duration)
        return LensRunResult(
            success=True,
            exit_code=0,
            duration_seconds=duration,
            error_message=None,
        )


def _build_message(
    entry: RepoEntry,
    sha: str,
    changed_files: list[str] | None,
) -> str:
    """Construct the initial message sent to the CLI."""
    lines = [
        f"Repository: {entry.clone_path}",
        f"Database: {entry.db_path}",
        f"Current SHA: {sha}",
    ]

    if changed_files is None:
        lines.append("Mode: full analysis")
    else:
        lines.append(f"Mode: incremental ({len(changed_files)} changed files)")
        display = changed_files[:_MAX_CHANGED_FILES_IN_MESSAGE]
        lines.append("Changed files:")
        for f in display:
            lines.append(f"  - {f}")
        if len(changed_files) > _MAX_CHANGED_FILES_IN_MESSAGE:
            lines.append(f"  ... and {len(changed_files) - _MAX_CHANGED_FILES_IN_MESSAGE} more")

    return "\n".join(lines)


def make_lens_callback(
    runner: LensRunner,
) -> Callable[[RepoEntry, PullResult], None]:
    """Create a callback suitable for the daemon's post-pull hook.

    The returned function iterates over the entry's enabled lenses and runs
    each one.  It keeps ``LensRunner`` ignorant of ``PullResult`` internals,
    and the daemon ignorant of lens mechanics.
    """

    def _callback(entry: RepoEntry, pull_result: PullResult) -> None:
        for lens_name in entry.enabled_lenses:
            runner.run(
                entry.slug,
                lens_name,
                changed_files=pull_result.changed_files or None,
            )

    return _callback

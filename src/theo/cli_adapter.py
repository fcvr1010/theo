"""CLI adapter abstraction for LensRunner.

    CLIAdapter (Protocol) -- interface for CLI-specific command construction.
    CLICommand(cmd, temp_files) -- command and temp files to clean up.
    ClaudeCodeAdapter(allowed_tools, dangerously_skip_permissions) -- Claude Code implementation.

Supports the strategy pattern: LensRunner delegates command construction to
the adapter, keeping CLI-specific details out of the runner itself.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CLICommand:
    """A fully constructed CLI command ready for subprocess execution.

    Attributes:
        cmd: The command and arguments as a list of strings.
        temp_files: Paths to temporary files the caller must clean up after execution.
    """

    cmd: list[str]
    temp_files: list[str] = field(default_factory=list)


@runtime_checkable
class CLIAdapter(Protocol):
    """Protocol for CLI-specific command construction.

    Each implementation knows how to turn a system prompt and a user message
    into a complete CLI invocation for a particular AI provider.
    """

    def build_command(self, system_prompt: str, message: str) -> CLICommand:
        """Build a CLI command from a system prompt and user message.

        The caller is responsible for cleaning up any files listed in
        ``CLICommand.temp_files`` after execution completes.

        Args:
            system_prompt: The full text of the system prompt.
            message: The user message to send to the CLI.

        Returns:
            A ``CLICommand`` ready for subprocess execution.
        """
        ...


class ClaudeCodeAdapter:
    """CLI adapter for the ``claude`` (Claude Code) CLI.

    Flags reference:
        - ``--system-prompt-file <path>``: reads system prompt from a file.
        - ``--print``: non-interactive output mode.
        - ``--allowedTools "<tool> <tool> ..."``: whitelist of allowed tools.
        - ``--dangerously-skip-permissions``: bypass all permission prompts.
        - Message is passed as a trailing positional argument (last, after all flags).

    Permission configuration is optional. By default, no permission flags are
    emitted and the CLI runs in its default interactive-permission mode.

    Args:
        cli_command: The CLI executable name or path (default: ``"claude"``).
        allowed_tools: Optional list of tool names to allow
            (e.g. ``["Bash", "Read", "Write"]``).
        dangerously_skip_permissions: If ``True``, pass
            ``--dangerously-skip-permissions`` to bypass all permission prompts.
            Mutually exclusive with ``allowed_tools``.
    """

    def __init__(
        self,
        cli_command: str = "claude",
        allowed_tools: list[str] | None = None,
        dangerously_skip_permissions: bool = False,
    ) -> None:
        if allowed_tools and dangerously_skip_permissions:
            raise ValueError(
                "Cannot specify both allowed_tools and dangerously_skip_permissions; "
                "choose one permission strategy."
            )
        self._cli_command = cli_command
        self._allowed_tools = allowed_tools
        self._dangerously_skip_permissions = dangerously_skip_permissions

    def build_command(self, system_prompt: str, message: str) -> CLICommand:
        """Build a ``claude`` CLI command.

        Writes the system prompt to a temporary file and returns a command
        with ``--system-prompt-file``, optional permission flags, ``--print``,
        and the message as a trailing positional argument.
        """
        # Write system prompt to a temp file (caller cleans up via temp_files).
        fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="theo-prompt-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(system_prompt)

        cmd: list[str] = [self._cli_command]

        # System prompt file.
        cmd.extend(["--system-prompt-file", tmp_path])

        # Output mode.
        cmd.append("--print")

        # Permission flags.
        if self._dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        elif self._allowed_tools:
            cmd.extend(["--allowedTools", " ".join(self._allowed_tools)])

        # Message as trailing positional argument (must be last).
        cmd.append(message)

        return CLICommand(cmd=cmd, temp_files=[tmp_path])


def adapter_for_config(cli_command: str) -> CLIAdapter:
    """Resolve a CLI adapter from a CLI command string.

    Currently supports:
        - ``"claude"`` (or any path ending in ``claude``): ``ClaudeCodeAdapter``

    Raises:
        ValueError: If the CLI command is not recognized.
    """
    basename = os.path.basename(cli_command)
    if basename == "claude":
        return ClaudeCodeAdapter(cli_command=cli_command)

    raise ValueError(
        f"Unsupported CLI command {cli_command!r}. "
        f"Supported: 'claude'. "
        f"Set THEO_CLI_COMMAND to a supported value."
    )

"""Tests for theo.cli_adapter."""

from __future__ import annotations

import os

import pytest

from theo.cli_adapter import (
    ClaudeCodeAdapter,
    CLIAdapter,
    CLICommand,
    adapter_for_config,
)

# ── CLICommand ────────────────────────────────────────────────────────────


class TestCLICommand:
    def test_frozen(self) -> None:
        cmd = CLICommand(cmd=["echo", "hello"])
        with pytest.raises(AttributeError):
            cmd.cmd = ["other"]  # type: ignore[misc]

    def test_defaults(self) -> None:
        cmd = CLICommand(cmd=["echo"])
        assert cmd.cmd == ["echo"]
        assert cmd.temp_files == []

    def test_with_temp_files(self) -> None:
        cmd = CLICommand(cmd=["claude"], temp_files=["/tmp/a.md", "/tmp/b.md"])
        assert cmd.temp_files == ["/tmp/a.md", "/tmp/b.md"]


# ── ClaudeCodeAdapter ─────────────────────────────────────────────────────


class TestClaudeCodeAdapter:
    def test_protocol_compliance(self) -> None:
        """ClaudeCodeAdapter satisfies the CLIAdapter protocol."""
        adapter = ClaudeCodeAdapter()
        assert isinstance(adapter, CLIAdapter)

    def test_basic_command_structure(self) -> None:
        adapter = ClaudeCodeAdapter()
        result = adapter.build_command("You are an architect.", "Analyze this repo")

        # CLI executable is first.
        assert result.cmd[0] == "claude"

        # --system-prompt-file with a temp file path.
        assert "--system-prompt-file" in result.cmd
        sp_idx = result.cmd.index("--system-prompt-file")
        tmp_path = result.cmd[sp_idx + 1]
        assert os.path.exists(tmp_path)
        assert tmp_path in result.temp_files

        # --print for non-interactive mode.
        assert "--print" in result.cmd

        # Message is the last positional argument.
        assert result.cmd[-1] == "Analyze this repo"

        # No permission flags by default.
        assert "--dangerously-skip-permissions" not in result.cmd
        assert "--allowedTools" not in result.cmd

        # Clean up.
        for f in result.temp_files:
            os.unlink(f)

    def test_system_prompt_file_contents(self) -> None:
        adapter = ClaudeCodeAdapter()
        result = adapter.build_command("Custom prompt text", "msg")

        sp_idx = result.cmd.index("--system-prompt-file")
        tmp_path = result.cmd[sp_idx + 1]

        with open(tmp_path, encoding="utf-8") as f:
            assert f.read() == "Custom prompt text"

        for f in result.temp_files:
            os.unlink(f)

    def test_custom_cli_command(self) -> None:
        adapter = ClaudeCodeAdapter(cli_command="/usr/local/bin/claude")
        result = adapter.build_command("prompt", "msg")

        assert result.cmd[0] == "/usr/local/bin/claude"

        for f in result.temp_files:
            os.unlink(f)

    def test_dangerously_skip_permissions(self) -> None:
        adapter = ClaudeCodeAdapter(dangerously_skip_permissions=True)
        result = adapter.build_command("prompt", "msg")

        assert "--dangerously-skip-permissions" in result.cmd
        # Message still last.
        assert result.cmd[-1] == "msg"

        for f in result.temp_files:
            os.unlink(f)

    def test_allowed_tools(self) -> None:
        adapter = ClaudeCodeAdapter(allowed_tools=["Bash", "Read", "Write"])
        result = adapter.build_command("prompt", "msg")

        assert "--allowedTools" in result.cmd
        at_idx = result.cmd.index("--allowedTools")
        assert result.cmd[at_idx + 1] == "Bash Read Write"
        # Message still last.
        assert result.cmd[-1] == "msg"

        for f in result.temp_files:
            os.unlink(f)

    def test_allowed_tools_and_skip_permissions_conflict(self) -> None:
        with pytest.raises(ValueError, match="Cannot specify both"):
            ClaudeCodeAdapter(
                allowed_tools=["Bash"],
                dangerously_skip_permissions=True,
            )

    def test_no_old_flags(self) -> None:
        """Verifies the two bugs are fixed: no --message, no --system-prompt (bare)."""
        adapter = ClaudeCodeAdapter()
        result = adapter.build_command("prompt", "msg")

        assert "--message" not in result.cmd
        # --system-prompt (without -file) should not appear.
        for _i, arg in enumerate(result.cmd):
            if arg == "--system-prompt":
                # This would be the old broken flag.
                pytest.fail("Found bare --system-prompt flag (should be --system-prompt-file)")

        for f in result.temp_files:
            os.unlink(f)

    def test_message_positional_after_all_flags(self) -> None:
        """Message must be the very last element, after all flags."""
        adapter = ClaudeCodeAdapter(
            allowed_tools=["Bash", "Read"],
            cli_command="claude",
        )
        result = adapter.build_command("prompt", "the user message")

        # Last element is the message.
        assert result.cmd[-1] == "the user message"

        # Every flag-like argument (starting with --) comes before the message.
        for i, arg in enumerate(result.cmd[:-1]):
            if arg.startswith("--"):
                assert i < len(result.cmd) - 1

        for f in result.temp_files:
            os.unlink(f)

    def test_each_call_creates_fresh_temp_file(self) -> None:
        adapter = ClaudeCodeAdapter()
        r1 = adapter.build_command("prompt1", "msg1")
        r2 = adapter.build_command("prompt2", "msg2")

        assert r1.temp_files[0] != r2.temp_files[0]

        for f in r1.temp_files + r2.temp_files:
            os.unlink(f)


# ── adapter_for_config ────────────────────────────────────────────────────


class TestAdapterForConfig:
    def test_claude(self) -> None:
        adapter = adapter_for_config("claude")
        assert isinstance(adapter, ClaudeCodeAdapter)

    def test_claude_full_path(self) -> None:
        adapter = adapter_for_config("/usr/local/bin/claude")
        assert isinstance(adapter, ClaudeCodeAdapter)

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported CLI command"):
            adapter_for_config("codex")

    def test_unknown_full_path_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported CLI command"):
            adapter_for_config("/usr/bin/codex")

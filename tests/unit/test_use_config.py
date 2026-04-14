"""Unit tests for the ``theo use`` command (real filesystem with tmp_path)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from theo._schema import CSV_FILES
from theo.cli.use import run


def test_creates_config_json(tmp_path: Path) -> None:
    run(str(tmp_path))
    config_path = tmp_path / ".theo" / "config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["project_slug"] == tmp_path.name
    assert config["db_path"] == ".theo/db/theo.db"
    assert config["last_indexed_commit"] is None
    assert "created" in config


def test_creates_all_csv_files(tmp_path: Path) -> None:
    run(str(tmp_path))
    for csv_name in CSV_FILES.values():
        csv_path = tmp_path / ".theo" / csv_name
        assert csv_path.exists(), f"Missing CSV: {csv_name}"


def test_creates_database(tmp_path: Path) -> None:
    run(str(tmp_path))
    db_path = tmp_path / ".theo" / "db" / "theo.db"
    assert db_path.exists()


def test_appends_gitignore(tmp_path: Path) -> None:
    run(str(tmp_path))
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert ".theo/db/" in content


def test_idempotent_gitignore(tmp_path: Path) -> None:
    run(str(tmp_path))
    run(str(tmp_path))
    gitignore = tmp_path / ".gitignore"
    content = gitignore.read_text()
    assert content.count(".theo/db/") == 1


def test_idempotent_no_errors(tmp_path: Path) -> None:
    """Running ``theo use`` twice should not raise."""
    run(str(tmp_path))
    run(str(tmp_path))


def test_creates_mcp_json(tmp_path: Path) -> None:
    run(str(tmp_path))
    mcp_path = tmp_path / ".mcp.json"
    assert mcp_path.exists()
    mcp = json.loads(mcp_path.read_text())
    assert "mcpServers" in mcp
    assert "theo" in mcp["mcpServers"]
    server = mcp["mcpServers"]["theo"]
    assert server["type"] == "stdio"
    assert "serve" in server.get("args", [])
    assert str(tmp_path) in server.get("args", [])


def test_creates_claude_skill_files(tmp_path: Path) -> None:
    run(str(tmp_path))
    skill_dir = tmp_path / ".claude" / "skills" / "theo"
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").exists()


def test_creates_agents_skill_files(tmp_path: Path) -> None:
    run(str(tmp_path))
    skill_dir = tmp_path / ".agents" / "skills" / "theo"
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").exists()


def test_preserves_existing_config_on_rerun(tmp_path: Path) -> None:
    run(str(tmp_path))
    config_path = tmp_path / ".theo" / "config.json"
    config = json.loads(config_path.read_text())
    original_created = config["created"]

    # Modify a field
    config["last_indexed_commit"] = "abc123"
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    run(str(tmp_path))
    config2 = json.loads(config_path.read_text())
    assert config2["last_indexed_commit"] == "abc123"
    assert config2["created"] == original_created


def test_appends_to_existing_gitignore(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\n")
    run(str(tmp_path))
    content = gitignore.read_text()
    assert "*.pyc" in content
    assert ".theo/db/" in content


def test_preserves_existing_mcp_servers(tmp_path: Path) -> None:
    """Re-running ``theo use`` preserves other MCP servers in ``.mcp.json``."""
    existing = {
        "mcpServers": {
            "other-server": {"command": "other", "args": [], "type": "stdio"},
        },
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(existing, indent=2) + "\n")

    run(str(tmp_path))

    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    assert "other-server" in mcp["mcpServers"]
    assert "theo" in mcp["mcpServers"]
    assert mcp["mcpServers"]["theo"]["type"] == "stdio"
    assert "serve" in mcp["mcpServers"]["theo"].get("args", [])


def test_updates_theo_entry_on_rerun(tmp_path: Path) -> None:
    """Re-running ``theo use`` updates the ``mcpServers.theo`` entry."""
    run(str(tmp_path))
    mcp1 = json.loads((tmp_path / ".mcp.json").read_text())
    assert "theo" in mcp1["mcpServers"]

    # Re-run and verify theo entry is still correct
    run(str(tmp_path))
    mcp2 = json.loads((tmp_path / ".mcp.json").read_text())
    assert "theo" in mcp2["mcpServers"]
    assert mcp2["mcpServers"]["theo"]["type"] == "stdio"


def test_creates_codex_config_toml(tmp_path: Path) -> None:
    run(str(tmp_path))
    config_path = tmp_path / ".codex" / "config.toml"
    assert config_path.exists()
    parsed = tomllib.loads(config_path.read_text())
    server = parsed["mcp_servers"]["theo"]
    assert "command" in server
    assert "serve" in server["args"]
    assert str(tmp_path) in server["args"]


def test_preserves_existing_codex_config(tmp_path: Path) -> None:
    """Re-running ``theo use`` preserves unrelated content in ``.codex/config.toml``."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    existing = (
        "# user comment\n"
        'model = "gpt-5"\n'
        "\n"
        "[mcp_servers.other]\n"
        'command = "other"\n'
        'args = ["--foo"]\n'
    )
    (codex_dir / "config.toml").write_text(existing)

    run(str(tmp_path))

    content = (codex_dir / "config.toml").read_text()
    assert "# user comment" in content
    parsed = tomllib.loads(content)
    assert parsed["model"] == "gpt-5"
    assert parsed["mcp_servers"]["other"]["command"] == "other"
    assert parsed["mcp_servers"]["other"]["args"] == ["--foo"]
    assert "theo" in parsed["mcp_servers"]
    assert "serve" in parsed["mcp_servers"]["theo"]["args"]


def test_codex_config_idempotent(tmp_path: Path) -> None:
    """Re-running ``theo use`` does not duplicate the theo MCP entry."""
    run(str(tmp_path))
    first = (tmp_path / ".codex" / "config.toml").read_text()
    run(str(tmp_path))
    second = (tmp_path / ".codex" / "config.toml").read_text()

    # Only one [mcp_servers.theo] header present
    assert second.count("[mcp_servers.theo]") == 1
    # TOML content is parseable and the theo entry is intact
    parsed = tomllib.loads(second)
    assert "theo" in parsed["mcp_servers"]
    assert first.count("[mcp_servers.theo]") == 1


def test_codex_config_replaces_stale_theo_entry(tmp_path: Path) -> None:
    """A stale ``[mcp_servers.theo]`` entry is replaced, not duplicated."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    stale = (
        "[mcp_servers.theo]\n"
        'command = "/old/path/to/theo"\n'
        'args = ["serve", "/old/project"]\n'
        "\n"
        "[mcp_servers.theo.env]\n"
        'FOO = "bar"\n'
    )
    (codex_dir / "config.toml").write_text(stale)

    run(str(tmp_path))

    content = (codex_dir / "config.toml").read_text()
    assert content.count("[mcp_servers.theo]") == 1
    assert "/old/path/to/theo" not in content
    assert "/old/project" not in content
    # Stale subtable is removed too
    assert "[mcp_servers.theo.env]" not in content
    parsed = tomllib.loads(content)
    assert str(tmp_path) in parsed["mcp_servers"]["theo"]["args"]

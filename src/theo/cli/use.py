"""``theo use`` -- initialise Theo in a project directory."""

from __future__ import annotations

import importlib.resources
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer

from theo._db import init_schema
from theo._schema import CSV_FILES


def _write_skill_files(dest_dir: Path) -> None:
    """Copy bundled ``.md`` skill files from the package into *dest_dir*."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    skill_pkg = importlib.resources.files("theo.skills").joinpath("theo")
    for item in skill_pkg.iterdir():
        if item.name.endswith(".md"):
            dest_dir.joinpath(item.name).write_text(item.read_text(encoding="utf-8"))


def _find_theo_executable() -> list[str]:
    """Return the command list for the ``theo`` executable."""
    exe = shutil.which("theo")
    if exe:
        return [exe]
    return [sys.executable, "-m", "theo.cli.main"]


def _toml_quote(s: str) -> str:
    """Encode *s* as a TOML basic string."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_codex_theo_block(theo_cmd: list[str], project_dir_str: str) -> str:
    """Return the ``[mcp_servers.theo]`` TOML block for Codex config."""
    if len(theo_cmd) == 1:
        command = theo_cmd[0]
        args = ["serve", project_dir_str]
    else:
        command = theo_cmd[0]
        args = [*theo_cmd[1:], "serve", project_dir_str]
    args_str = ", ".join(_toml_quote(a) for a in args)
    return f"[mcp_servers.theo]\ncommand = {_toml_quote(command)}\nargs = [{args_str}]\n"


def _strip_codex_theo_section(content: str) -> str:
    """Remove any existing ``[mcp_servers.theo]`` (and subtables) from *content*.

    Text-based surgery so we don't disturb comments or formatting of unrelated
    sections in the user's config.
    """
    header_re = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
    out: list[str] = []
    skipping = False
    for line in content.splitlines(keepends=True):
        m = header_re.match(line)
        if m:
            section = m.group(1).strip()
            if section == "mcp_servers.theo" or section.startswith("mcp_servers.theo."):
                skipping = True
                continue
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


AGENTS_MD_SECTION = (
    "# Theo\n"
    "\n"
    "Use the theo skill to plan modifications to the code, understand dependencies "
    "and pitfalls. Once changes are done, use the theo skill to update theo's "
    "codebase intelligence.\n"
)


def _strip_agents_md_theo_section(content: str) -> str:
    """Remove any existing ``# Theo`` section (up to the next top-level heading)."""
    out: list[str] = []
    skipping = False
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            if heading.casefold() == "theo":
                skipping = True
                continue
            if skipping:
                skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


def _update_agents_md(project_dir: Path) -> None:
    """Append (or refresh) the ``# Theo`` section in ``AGENTS.md``."""
    agents_md = project_dir / "AGENTS.md"
    if agents_md.exists():
        cleaned = _strip_agents_md_theo_section(agents_md.read_text()).rstrip()
        new_content = cleaned + "\n\n" + AGENTS_MD_SECTION if cleaned else AGENTS_MD_SECTION
    else:
        new_content = AGENTS_MD_SECTION
    agents_md.write_text(new_content)


def _update_codex_mcp_config(project_dir: Path, theo_cmd: list[str], project_dir_str: str) -> None:
    """Register Theo's MCP server in ``.codex/config.toml``.

    See https://developers.openai.com/codex/mcp for the expected TOML schema.
    Preserves any pre-existing configuration in the file.
    """
    codex_dir = project_dir / ".codex"
    codex_dir.mkdir(exist_ok=True)
    config_path = codex_dir / "config.toml"
    theo_block = _build_codex_theo_block(theo_cmd, project_dir_str)

    if config_path.exists():
        cleaned = _strip_codex_theo_section(config_path.read_text()).rstrip()
        new_content = cleaned + "\n\n" + theo_block if cleaned else theo_block
    else:
        new_content = theo_block

    config_path.write_text(new_content)


def run(project_dir_str: str) -> None:
    """Execute the ``theo use`` initialisation workflow."""
    project_dir = Path(project_dir_str).resolve()
    if not project_dir.is_dir():
        typer.echo(f"Error: '{project_dir}' is not a directory.", err=True)
        raise typer.Exit(1)

    theo_dir = project_dir / ".theo"
    theo_dir.mkdir(exist_ok=True)

    # Create empty CSV files (idempotent -- only if they don't already exist)
    for csv_name in CSV_FILES.values():
        csv_path = theo_dir / csv_name
        if not csv_path.exists():
            csv_path.touch()

    # Initialise the database
    db_dir = theo_dir / "db"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / "theo.db"
    if not db_path.exists():
        init_schema(db_path)

    # Write config.json (preserve existing values on re-run)
    config_path = theo_dir / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        config = {
            "project_slug": project_dir.name,
            "db_path": ".theo/db/theo.db",
            "last_indexed_commit": None,
            "created": datetime.now(UTC).isoformat(),
        }
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    # Append .theo/db/ to .gitignore (idempotent)
    gitignore = project_dir / ".gitignore"
    marker = ".theo/db/"
    if gitignore.exists():
        content = gitignore.read_text()
        if marker not in content:
            # Ensure we start on a new line
            if content and not content.endswith("\n"):
                content += "\n"
            content += marker + "\n"
            gitignore.write_text(content)
    else:
        gitignore.write_text(marker + "\n")

    # Register MCP server in .mcp.json (project root)
    mcp_json_path = project_dir / ".mcp.json"
    theo_cmd = _find_theo_executable()
    project_dir_str = str(project_dir)
    if len(theo_cmd) == 1:
        theo_server = {
            "command": theo_cmd[0],
            "args": ["serve", project_dir_str],
            "type": "stdio",
        }
    else:
        theo_server = {
            "command": theo_cmd[0],
            "args": [*theo_cmd[1:], "serve", project_dir_str],
            "type": "stdio",
        }
    if mcp_json_path.exists():
        existing = json.loads(mcp_json_path.read_text())
        existing.setdefault("mcpServers", {})["theo"] = theo_server
        mcp_json_path.write_text(json.dumps(existing, indent=2) + "\n")
    else:
        mcp_config = {"mcpServers": {"theo": theo_server}}
        mcp_json_path.write_text(json.dumps(mcp_config, indent=2) + "\n")

    # Register MCP server in .codex/config.toml (Codex CLI / IDE extension)
    _update_codex_mcp_config(project_dir, theo_cmd, project_dir_str)

    # Write skill files to .claude/skills/theo/
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)
    _write_skill_files(claude_dir / "skills" / "theo")

    # Write skill files to .agents/skills/theo/ (Cursor/Codex future compat)
    _write_skill_files(project_dir / ".agents" / "skills" / "theo")

    # Ensure AGENTS.md mentions the theo skill (cross-tool instruction file)
    _update_agents_md(project_dir)

    typer.echo(f"Theo initialised in {project_dir}")

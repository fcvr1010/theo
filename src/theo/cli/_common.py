"""Shared bootstrap helpers for CLI commands that operate on a loaded project.

Every subcommand that reads or writes an existing Theo project needs the same
preamble: find the project root, read ``.theo/config.json``, and resolve the
DB + CSV paths.  Two reviews in a row flagged that preamble as copy-paste
across ``reindex``, ``reload``, ``ui`` and ``serve``; this module is the
single funnel they all go through.

``theo use`` is *not* a client of this module: it creates the project rather
than loading an existing one, so it has nothing to share.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from theo._db import migrate_embedding_column, rebuild_from_csv
from theo._git import find_theo_root
from theo._schema import CSV_FILES, NODE_TABLES


@dataclass(frozen=True)
class Project:
    """Resolved filesystem handles + config dict for an existing Theo project.

    Callers should treat this as read-only — any mutation of the underlying
    files should go through the normal CLI / MCP entry points so the usual
    COW + CSV-export flow applies.
    """

    root: Path
    config_path: Path
    db_path: Path
    csv_dir: Path
    config: dict[str, Any]


def load_project(project_dir_str: str) -> Project:
    """Locate ``.theo/`` upward from *project_dir_str*, load config, resolve paths.

    Exits with a clear error on stderr (``typer.Exit(1)``) if no project is
    found — callers should treat this as terminal for the current CLI
    invocation rather than catching it.
    """
    project_dir = Path(project_dir_str).resolve()
    root = find_theo_root(project_dir)
    if root is None:
        typer.echo("Error: no .theo/config.json found (searched upward).", err=True)
        raise typer.Exit(1)

    config_path = root / ".theo" / "config.json"
    config = json.loads(config_path.read_text())
    db_path = (root / config["db_path"]).resolve()
    csv_dir = root / ".theo"
    return Project(
        root=root,
        config_path=config_path,
        db_path=db_path,
        csv_dir=csv_dir,
        config=config,
    )


def ensure_db(project: Project) -> None:
    """Make the runtime DB usable without requiring a prior ``theo use``.

    If the DB file is missing but node-table CSVs are populated, rebuilds
    from CSVs (the CSVs are the source of truth on disk).  Then runs the
    idempotent embedding-column migration so pre-branch DBs gain the
    ``embedding`` column without a full rebuild.  Exits with an error if the
    DB is missing *and* there is no CSV data to rebuild from.

    Used by ``serve`` and ``ui`` where self-healing is more valuable than a
    strict "did the user run 'theo use' yet?" check; ``reindex`` and
    ``reload`` intentionally don't call this because they already own a more
    specific missing-DB failure mode.
    """
    if not project.db_path.exists():
        required_csvs = [CSV_FILES[t] for t in NODE_TABLES]
        has_csvs = any(
            (project.csv_dir / f).exists() and (project.csv_dir / f).stat().st_size > 0
            for f in required_csvs
        )
        if not has_csvs:
            typer.echo(
                "Error: database not found and no CSV data to rebuild from.",
                err=True,
            )
            raise typer.Exit(1)
        project.db_path.parent.mkdir(parents=True, exist_ok=True)
        rebuild_from_csv(project.db_path, project.csv_dir)

    migrate_embedding_column(project.db_path)

"""``theo reindex`` -- recompute semantic embeddings for every node and edge.

Useful when:
- Switching the embedding model (indexes need rebuilding).
- Auto-index was disabled or failed for a batch of writes.
- Migrating an older DB that had no ``embedding`` column.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from theo._db import migrate_embedding_column, reindex_all
from theo._embed import is_available
from theo._git import find_theo_root


def run(project_dir_str: str) -> None:
    """Rebuild embeddings for the project at *project_dir_str*."""
    project_dir = Path(project_dir_str).resolve()
    root = find_theo_root(project_dir)
    if root is None:
        typer.echo("Error: no .theo/config.json found (searched upward).", err=True)
        raise typer.Exit(1)

    config_path = root / ".theo" / "config.json"
    config = json.loads(config_path.read_text())
    db_path = root / config["db_path"]
    if not db_path.exists():
        typer.echo(f"Error: database not found at {db_path}. Run 'theo use' first.", err=True)
        raise typer.Exit(1)

    if not is_available():
        typer.echo(
            "Error: fastembed is not installed. Install with: pip install 'theo[semantic]'.",
            err=True,
        )
        raise typer.Exit(1)

    # Guarantee the embedding column exists on older DBs.
    migrate_embedding_column(db_path)

    typer.echo("Reindexing embeddings...")
    counts = reindex_all(db_path)
    typer.echo("")
    typer.echo("Per-table counts:")
    for table, n in counts.items():
        typer.echo(f"  {table:20s} {n:>6d}")

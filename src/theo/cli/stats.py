"""``theo stats`` -- print graph health info to the terminal."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from theo._db import get_stats
from theo._git import find_theo_root, head_commit


def run(project_dir_str: str) -> None:
    """Print graph statistics and freshness information."""
    project_dir = Path(project_dir_str).resolve()
    root = find_theo_root(project_dir)
    if root is None:
        typer.echo("Error: no .theo/config.json found (searched upward).", err=True)
        raise typer.Exit(1)

    config_path = root / ".theo" / "config.json"
    config = json.loads(config_path.read_text())
    db_path = root / config["db_path"]

    if not db_path.exists():
        typer.echo("Error: database not found. Run 'theo use' first.", err=True)
        raise typer.Exit(1)

    stats = get_stats(db_path)
    last_indexed = config.get("last_indexed_commit")
    head = head_commit(root)
    is_stale = last_indexed is None or last_indexed != head

    typer.echo("Theo Graph Statistics")
    typer.echo("=" * 40)
    typer.echo("")
    typer.echo("Node counts:")
    for table, count in stats["node_counts"].items():
        typer.echo(f"  {table:20s} {count:>6d}")
    typer.echo("")
    typer.echo("Edge counts:")
    for rel, count in stats["edge_counts"].items():
        typer.echo(f"  {rel:20s} {count:>6d}")
    typer.echo("")
    typer.echo(f"Last indexed commit:  {last_indexed or '(none)'}")
    typer.echo(f"Current HEAD:         {head or '(not a git repo)'}")
    typer.echo(f"Stale:                {'yes' if is_stale else 'no'}")

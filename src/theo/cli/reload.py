"""``theo reload`` -- rebuild the runtime DB from the on-disk CSV files.

Use this after editing the ``.theo/*.csv`` files by hand (or pulling changes
that touch them). The KuzuDB file is dropped and regenerated from the CSVs,
which are the source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from theo._db import get_stats, rebuild_from_csv
from theo._git import find_theo_root
from theo._schema import CSV_FILES


def run(project_dir_str: str) -> None:
    """Rebuild the runtime KuzuDB from the CSV files in ``.theo/``."""
    project_dir = Path(project_dir_str).resolve()
    root = find_theo_root(project_dir)
    if root is None:
        typer.echo("Error: no .theo/config.json found (searched upward).", err=True)
        raise typer.Exit(1)

    config_path = root / ".theo" / "config.json"
    config = json.loads(config_path.read_text())
    db_path = root / config["db_path"]
    csv_dir = root / ".theo"

    # At least the two node-table CSVs must be present; empty is fine (fresh project).
    missing = [
        CSV_FILES[t] for t in ("Concept", "SourceFile") if not (csv_dir / CSV_FILES[t]).exists()
    ]
    if missing:
        typer.echo(
            f"Error: missing required CSV file(s): {', '.join(missing)}",
            err=True,
        )
        raise typer.Exit(1)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    rebuild_from_csv(db_path, csv_dir)

    stats = get_stats(db_path)
    typer.echo(f"Reloaded {db_path} from CSVs in {csv_dir}.")
    typer.echo("")
    typer.echo("Node counts:")
    for table, count in stats["node_counts"].items():
        typer.echo(f"  {table:20s} {count:>6d}")
    typer.echo("")
    typer.echo("Edge counts:")
    for rel, count in stats["edge_counts"].items():
        typer.echo(f"  {rel:20s} {count:>6d}")

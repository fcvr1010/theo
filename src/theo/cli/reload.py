"""``theo reload`` -- rebuild the runtime DB from the on-disk CSV files.

Use this after editing the ``.theo/*.csv`` files by hand (or pulling changes
that touch them). The KuzuDB file is dropped and regenerated from the CSVs,
which are the source of truth.
"""

from __future__ import annotations

import typer

from theo._db import get_stats, rebuild_from_csv, reindex_all
from theo._schema import CSV_FILES, NODE_TABLES
from theo.cli._common import load_project


def run(project_dir_str: str) -> None:
    """Rebuild the runtime KuzuDB from the CSV files in ``.theo/``."""
    project = load_project(project_dir_str)

    # At least the node-table CSVs must be present; empty is fine (fresh project).
    missing = [CSV_FILES[t] for t in NODE_TABLES if not (project.csv_dir / CSV_FILES[t]).exists()]
    if missing:
        typer.echo(
            f"Error: missing required CSV file(s): {', '.join(missing)}",
            err=True,
        )
        raise typer.Exit(1)

    project.db_path.parent.mkdir(parents=True, exist_ok=True)
    rebuild_from_csv(project.db_path, project.csv_dir)

    counts = reindex_all(project.db_path)
    if any(n > 0 for n in counts.values()):
        typer.echo("Reindexed embeddings:")
        for table, n in counts.items():
            if n > 0:
                typer.echo(f"  {table:20s} {n:>6d}")

    stats = get_stats(project.db_path)
    typer.echo(f"Reloaded {project.db_path} from CSVs in {project.csv_dir}.")
    typer.echo("")
    typer.echo("Node counts:")
    for table, count in stats["node_counts"].items():
        typer.echo(f"  {table:20s} {count:>6d}")
    typer.echo("")
    typer.echo("Edge counts:")
    for rel, count in stats["edge_counts"].items():
        typer.echo(f"  {rel:20s} {count:>6d}")

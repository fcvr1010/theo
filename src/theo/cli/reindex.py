"""``theo reindex`` -- recompute semantic embeddings for every node and edge.

Run this after a batch of ``theo_upsert_node`` / ``theo_upsert_edge`` calls
to refresh the semantic index -- upserts do not embed on write.  Also the
right entry point when switching embedding models, or migrating an older DB
that had no ``embedding`` column.
"""

from __future__ import annotations

import typer

from theo._db import migrate_embedding_column, reindex_all
from theo._embed import prewarm_model
from theo.cli._common import load_project


def run(project_dir_str: str) -> None:
    """Rebuild embeddings for the project at *project_dir_str*."""
    project = load_project(project_dir_str)
    if not project.db_path.exists():
        typer.echo(
            f"Error: database not found at {project.db_path}. "
            "Run 'theo use' to initialise, or 'theo reload' to rebuild from CSVs.",
            err=True,
        )
        raise typer.Exit(1)

    # Guarantee the embedding column exists on older DBs.
    migrate_embedding_column(project.db_path)

    # Warm the model up front so the user sees an explicit "Loading model..."
    # message rather than a misleading silent pause after "Reindexing
    # embeddings...".  fastembed cold start is ~2 s on first use of a fresh
    # checkout (downloads/loads ONNX weights); subsequent invocations are
    # near-instant once the model is cached.
    typer.echo("Loading embedding model...")
    prewarm_model()

    typer.echo("Reindexing embeddings...")
    counts = reindex_all(project.db_path)
    typer.echo("")
    typer.echo("Per-table counts:")
    for table, n in counts.items():
        typer.echo(f"  {table:20s} {n:>6d}")

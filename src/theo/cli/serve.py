"""``theo serve`` -- MCP server with stdio transport.

Exposes six tools: ``theo_stats``, ``theo_query``, ``theo_upsert_node``,
``theo_upsert_edge``, ``theo_delete_node``, and ``theo_delete_edge``.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import typer

from theo._cow import abort_write, begin_write, commit_write
from theo._db import (
    delete_edge,
    delete_node,
    export_csv,
    get_stats,
    rebuild_from_csv,
    run_query,
    upsert_edge,
    upsert_node,
)
from theo._git import find_theo_root, head_commit
from theo._schema import NODE_TABLES, PK_MAP, REL_TABLES


def _load_config(project_dir: Path) -> dict[str, Any]:
    """Find and load ``.theo/config.json``, searching upward from *project_dir*."""
    root = find_theo_root(project_dir)
    if root is None:
        typer.echo("Error: no .theo/config.json found (searched upward).", err=True)
        raise typer.Exit(1)
    config_path = root / ".theo" / "config.json"
    return {**json.loads(config_path.read_text()), "_root": str(root)}


def _resolve_paths(config: dict[str, Any]) -> tuple[Path, Path]:
    """Return (db_path, csv_dir) resolved from config."""
    root = Path(config["_root"])
    db_path = root / config["db_path"]
    csv_dir = root / ".theo"
    return db_path, csv_dir


def _ensure_db(db_path: Path, csv_dir: Path) -> None:
    """Rebuild the DB from CSVs if the DB is missing but CSVs exist."""
    if db_path.exists():
        return
    has_csvs = any(
        (csv_dir / f).exists() and (csv_dir / f).stat().st_size > 0
        for f in ["concepts.csv", "source_files.csv"]
    )
    if has_csvs:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        rebuild_from_csv(db_path, csv_dir)
    else:
        typer.echo(
            "Error: database not found and no CSV data to rebuild from.",
            err=True,
        )
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Tool handler functions (extracted for testability)
# ---------------------------------------------------------------------------


def handle_theo_stats(
    db_path: Path,
    csv_dir: Path,
    config_path: Path,
) -> dict[str, Any]:
    """Return graph statistics and freshness check.

    Re-reads ``config.json`` from disk on every call so that
    ``last_indexed_commit`` is always fresh.
    """
    with open(config_path) as f:
        config: dict[str, Any] = json.load(f)
    root = config_path.parent.parent  # .theo/config.json -> project root
    stats = get_stats(db_path)
    last_indexed = config.get("last_indexed_commit")
    head = head_commit(root)
    is_stale = last_indexed is None or last_indexed != head
    return {
        **stats,
        "last_indexed_commit": last_indexed,
        "head_commit": head,
        "is_stale": is_stale,
    }


def handle_theo_query(db_path: Path, cypher: str) -> list[dict[str, Any]]:
    """Execute a read-only Cypher query against the knowledge graph."""
    return run_query(db_path, cypher)


def handle_theo_upsert_node(
    db_path: Path,
    csv_dir: Path,
    table: str,
    properties: dict[str, Any],
) -> dict[str, Any]:
    """Upsert a node (COW -> export CSV)."""
    if table not in NODE_TABLES:
        return {
            "status": "error",
            "detail": f"Invalid table: {table}. Must be one of {NODE_TABLES}",
        }

    pk_field = PK_MAP[table]
    if pk_field not in properties:
        return {"status": "error", "detail": f"Missing primary key field '{pk_field}'"}

    tmp_path = begin_write(db_path)
    try:
        result = upsert_node(tmp_path, table, properties)
        if result["status"] == "error":
            abort_write(tmp_path)
            return result
        commit_write(tmp_path, db_path)
        export_csv(db_path, csv_dir)
        return {"status": "ok", "table": table, "id": properties[pk_field]}
    except Exception as exc:
        with contextlib.suppress(Exception):
            abort_write(tmp_path)
        return {"status": "error", "detail": str(exc)}


def handle_theo_upsert_edge(
    db_path: Path,
    csv_dir: Path,
    rel_type: str,
    from_id: str,
    to_id: str,
    description: str | None = None,
    *,
    git_revision: str,
) -> dict[str, Any]:
    """Upsert a relationship (COW -> export CSV)."""
    if rel_type not in REL_TABLES:
        return {
            "status": "error",
            "detail": f"Invalid relationship type: {rel_type}. Must be one of {REL_TABLES}",
        }

    tmp_path = begin_write(db_path)
    try:
        result = upsert_edge(
            tmp_path,
            rel_type,
            from_id,
            to_id,
            description,
            git_revision=git_revision,
        )
        if result["status"] == "error":
            abort_write(tmp_path)
            return result
        commit_write(tmp_path, db_path)
        export_csv(db_path, csv_dir)
        return {"status": "ok", "rel_type": rel_type, "from": from_id, "to": to_id}
    except Exception as exc:
        with contextlib.suppress(Exception):
            abort_write(tmp_path)
        return {"status": "error", "detail": str(exc)}


def handle_theo_delete_node(
    db_path: Path,
    csv_dir: Path,
    table: str,
    id: str,
    *,
    detach: bool = False,
) -> dict[str, Any]:
    """Delete a node (COW -> export CSV)."""
    if table not in NODE_TABLES:
        return {
            "status": "error",
            "detail": f"Invalid table: {table}. Must be one of {NODE_TABLES}",
        }

    tmp_path = begin_write(db_path)
    try:
        result = delete_node(tmp_path, table, id, detach=detach)
        if result["status"] == "error":
            abort_write(tmp_path)
            return result
        commit_write(tmp_path, db_path)
        export_csv(db_path, csv_dir)
        return result
    except Exception as exc:
        with contextlib.suppress(Exception):
            abort_write(tmp_path)
        return {"status": "error", "detail": str(exc)}


def handle_theo_delete_edge(
    db_path: Path,
    csv_dir: Path,
    rel_type: str,
    from_id: str,
    to_id: str,
) -> dict[str, Any]:
    """Delete a relationship (COW -> export CSV)."""
    if rel_type not in REL_TABLES:
        return {
            "status": "error",
            "detail": f"Invalid relationship type: {rel_type}. Must be one of {REL_TABLES}",
        }

    tmp_path = begin_write(db_path)
    try:
        result = delete_edge(tmp_path, rel_type, from_id, to_id)
        if result["status"] == "error":
            abort_write(tmp_path)
            return result
        commit_write(tmp_path, db_path)
        export_csv(db_path, csv_dir)
        return result
    except Exception as exc:
        with contextlib.suppress(Exception):
            abort_write(tmp_path)
        return {"status": "error", "detail": str(exc)}


# ---------------------------------------------------------------------------
# MCP server setup
# ---------------------------------------------------------------------------


def run(project_dir_str: str) -> None:
    """Start the MCP server."""
    from mcp.server.fastmcp import FastMCP

    project_dir = Path(project_dir_str).resolve()
    config = _load_config(project_dir)
    db_path, csv_dir = _resolve_paths(config)
    config_path = Path(config["_root"]) / ".theo" / "config.json"
    _ensure_db(db_path, csv_dir)

    mcp = FastMCP("theo")

    @mcp.tool()
    def theo_stats() -> dict[str, Any]:
        """Return graph statistics and freshness check.

        Returns a dict with node_counts, edge_counts, last_indexed_commit,
        head_commit, and is_stale fields.
        """
        try:
            return handle_theo_stats(db_path, csv_dir, config_path)
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    @mcp.tool()
    def theo_query(cypher: str) -> list[dict[str, Any]]:
        """Execute a read-only Cypher query against the knowledge graph.

        Returns a list of dicts, one per result row.
        """
        try:
            return handle_theo_query(db_path, cypher)
        except Exception as exc:
            return [{"status": "error", "detail": str(exc)}]

    @mcp.tool()
    def theo_upsert_node(table: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Upsert a node in the knowledge graph.

        Uses copy-on-write for safe mutation and exports CSVs after each write.
        ``table`` must be one of: Concept, SourceFile.
        ``properties`` must include the primary key field for the table.
        """
        return handle_theo_upsert_node(db_path, csv_dir, table, properties)

    @mcp.tool()
    def theo_upsert_edge(
        rel_type: str,
        from_id: str,
        to_id: str,
        git_revision: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Upsert a relationship in the knowledge graph.

        Uses copy-on-write for safe mutation and exports CSVs after each write.
        ``rel_type`` must be one of: PartOf, BelongsTo, InteractsWith, DependsOn, Imports.
        """
        return handle_theo_upsert_edge(
            db_path,
            csv_dir,
            rel_type,
            from_id,
            to_id,
            description,
            git_revision=git_revision,
        )

    @mcp.tool()
    def theo_delete_node(table: str, id: str, detach: bool = False) -> dict[str, Any]:
        """Delete a node from the knowledge graph.

        Uses copy-on-write for safe mutation and exports CSVs after each write.
        ``table`` must be one of: Concept, SourceFile. ``id`` is the primary
        key value (``id`` for Concept, ``path`` for SourceFile).

        Refuses if the node is a Concept that still has child Concepts (via
        PartOf) or owning SourceFiles (via BelongsTo) -- re-parent first.

        Refuses if the node has other incident edges unless ``detach=True`` is
        passed; with ``detach=True`` all incident edges are dropped together
        with the node.
        """
        return handle_theo_delete_node(db_path, csv_dir, table, id, detach=detach)

    @mcp.tool()
    def theo_delete_edge(rel_type: str, from_id: str, to_id: str) -> dict[str, Any]:
        """Delete a relationship from the knowledge graph.

        Uses copy-on-write for safe mutation and exports CSVs after each write.
        ``rel_type`` must be one of: PartOf, BelongsTo, InteractsWith,
        DependsOn, Imports.
        """
        return handle_theo_delete_edge(db_path, csv_dir, rel_type, from_id, to_id)

    mcp.run("stdio")

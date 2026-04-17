"""``theo serve`` -- MCP server with stdio transport.

Exposes eight tools: ``theo_stats``, ``theo_query``, ``theo_search``,
``theo_reload``, ``theo_upsert_node``, ``theo_upsert_edge``,
``theo_delete_node``, and ``theo_delete_edge``.
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any

import typer

from theo._cow import abort_write, begin_write, commit_write
from theo._db import (
    delete_edge,
    delete_node,
    export_csv,
    get_stats,
    migrate_embedding_column,
    rebuild_from_csv,
    reindex_all,
    run_query,
    semantic_search,
    upsert_edge,
    upsert_node,
    write_edge_embedding,
    write_node_embedding,
)
from theo._embed import (
    _get_model,
    embed_documents,
    embed_query,
    make_edge_text,
    make_node_text,
)
from theo._git import find_theo_root, head_commit
from theo._schema import CSV_FILES, EMBEDDABLE_TABLES, NODE_TABLES, PK_MAP, REL_TABLES

_log = logging.getLogger(__name__)


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
    """Rebuild the DB from CSVs if the DB is missing but CSVs exist.

    Also runs the idempotent embedding-column migration so older DBs gain the
    semantic column without a full rebuild.
    """
    if not db_path.exists():
        required_csvs = [CSV_FILES[t] for t in NODE_TABLES]
        has_csvs = any(
            (csv_dir / f).exists() and (csv_dir / f).stat().st_size > 0 for f in required_csvs
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

    migrate_embedding_column(db_path)


# ---------------------------------------------------------------------------
# Auto-indexing helpers
#
# Auto-index runs AFTER the COW commit + CSV export.  Embedding is a derived
# cache, so failures must never roll back a successful upsert: we swallow
# exceptions and log them.
# ---------------------------------------------------------------------------


def _auto_index_node(db_path: Path, table: str, properties: dict[str, Any]) -> None:
    """Best-effort: embed the node's text fields and store the vector."""
    text = make_node_text(properties.get("description"), properties.get("notes"))
    if not text:
        return
    try:
        vector = embed_documents([text])[0]
        write_node_embedding(db_path, table, properties[PK_MAP[table]], vector)
    except Exception:
        _log.exception("Auto-index failed for %s %s", table, properties.get(PK_MAP[table]))


def _auto_index_edge(
    db_path: Path,
    rel_type: str,
    from_id: str,
    to_id: str,
    description: str | None,
) -> None:
    """Best-effort: embed the edge's description and store the vector."""
    text = make_edge_text(description)
    if not text:
        return
    try:
        vector = embed_documents([text])[0]
        write_edge_embedding(db_path, rel_type, from_id, to_id, vector)
    except Exception:
        _log.exception("Auto-index failed for %s %s->%s", rel_type, from_id, to_id)


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


def handle_theo_search(
    db_path: Path,
    query: str,
    table: str | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """Semantic search over the knowledge graph.

    Returns ``{"status": "ok", "matches": [...]}`` where each match is a dict
    describing a node (``kind="node"``) or a relationship (``kind="edge"``)
    with its similarity ``score``.

    Returns ``{"status": "error", "detail": ...}`` if the table filter is
    invalid or the underlying query fails.
    """
    if table is not None and table not in EMBEDDABLE_TABLES:
        return {
            "status": "error",
            "detail": f"Invalid table: {table}. Must be one of {EMBEDDABLE_TABLES} or null.",
        }
    # ``top_k`` arrives from MCP as user-controlled input, and is interpolated
    # into Cypher's ``LIMIT``.  Coerce + clamp so malformed values fail cleanly
    # here rather than producing opaque Cypher errors downstream.
    try:
        top_k_int = int(top_k)
    except (TypeError, ValueError):
        return {"status": "error", "detail": f"top_k must be an integer, got: {top_k!r}"}
    if top_k_int < 1:
        return {"status": "error", "detail": f"top_k must be >= 1, got: {top_k_int}"}
    top_k_int = min(top_k_int, 1000)

    try:
        qvec = embed_query(query)
        matches = semantic_search(db_path, qvec, table, top_k_int)
        return {"status": "ok", "matches": matches}
    except Exception as exc:
        # Raw exception text is returned to the MCP client.  Safe today
        # because Theo's MCP runs over local stdio only — no network
        # exposure.  If the transport ever becomes networked, redact here
        # and log the full traceback internally instead.
        return {"status": "error", "detail": str(exc)}


def handle_theo_reload(db_path: Path, csv_dir: Path) -> dict[str, Any]:
    """Rebuild the runtime DB from the CSV files under ``csv_dir``.

    Running the reload through MCP (rather than shelling out to ``theo reload``)
    means the MCP server itself owns the rebuild — no external process races
    with the live server for DB access.

    Sequence: validate that CSVs exist → ``rebuild_from_csv`` →
    ``reindex_all`` so search is usable immediately.
    """
    required = [CSV_FILES[t] for t in NODE_TABLES]
    missing = [name for name in required if not (csv_dir / name).exists()]
    if missing:
        return {
            "status": "error",
            "detail": f"Missing required CSV file(s): {', '.join(missing)}",
        }
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        rebuild_from_csv(db_path, csv_dir)
    except Exception as exc:
        return {"status": "error", "detail": f"rebuild failed: {exc}"}

    try:
        reindex_counts = reindex_all(db_path)
    except Exception as exc:
        # The structural rebuild succeeded; only embeddings failed.
        _log.exception("reindex_all failed after rebuild")
        return {
            "status": "ok",
            "rebuilt": True,
            "reindex": {"status": "error", "detail": str(exc)},
            "stats": get_stats(db_path),
        }

    return {
        "status": "ok",
        "rebuilt": True,
        "reindex": reindex_counts,
        "stats": get_stats(db_path),
    }


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
        _auto_index_node(db_path, table, properties)
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
        _auto_index_edge(db_path, rel_type, from_id, to_id, description)
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

    # Pre-warm the embedding model so the first MCP write/search is not
    # blocked ~2 s on cold-start model load.
    with contextlib.suppress(Exception):
        _get_model()

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
    def theo_search(
        query: str,
        table: str | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Semantic search over the knowledge graph.

        Embeds ``query`` with a local ``nomic-embed-text-v1.5`` model, ranks
        every Concept, SourceFile, and relationship by cosine similarity, and
        returns the top ``top_k`` matches.

        Use for free-text / intent queries (e.g. "how are writes atomic?").
        For structural traversal, prefer ``theo_query``.

        ``table`` optionally restricts the search to one embeddable table
        ("Concept", "SourceFile", "PartOf", "BelongsTo", "InteractsWith",
        "DependsOn", "Imports") or ``null`` for all.
        """
        return handle_theo_search(db_path, query, table, top_k)

    @mcp.tool()
    def theo_reload() -> dict[str, Any]:
        """Rebuild the runtime DB from the on-disk CSV files.

        Use after pulling git changes that touch ``.theo/*.csv``, or after
        editing the CSVs by hand.  The rebuild happens inside the live MCP
        server so no external process races with it for DB access (as would
        happen if you shelled out to ``theo reload``).

        Embeddings are recomputed automatically so search is usable
        immediately after reload.

        Returns ``{"status": "ok", "rebuilt": true, "reindex": {...},
        "stats": {...}}``.
        """
        try:
            return handle_theo_reload(db_path, csv_dir)
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

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

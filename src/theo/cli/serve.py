"""``theo serve`` -- MCP server with stdio transport.

Exposes eight tools: ``theo_stats``, ``theo_query``, ``theo_search``,
``theo_reload``, ``theo_upsert_node``, ``theo_upsert_edge``,
``theo_delete_node``, and ``theo_delete_edge``.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from theo._cow import abort_write, begin_write, commit_write
from theo._db import (
    delete_edge,
    delete_node,
    export_csv,
    get_stats,
    rebuild_from_csv,
    reindex_all,
    run_query,
    semantic_search,
    upsert_edge,
    upsert_node,
)
from theo._embed import embed_query, prewarm_model
from theo._git import head_commit
from theo._schema import CSV_FILES, EMBEDDABLE_TABLES, NODE_TABLES
from theo.cli._common import ensure_db, load_project

_log = logging.getLogger(__name__)


def _run_write(
    db_path: Path,
    csv_dir: Path,
    op: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    """Run a single write ``op`` inside the standard COW → export lifecycle.

    ``op`` receives the temporary DB path and returns the status-dict shape
    that every ``_db.py`` write primitive already uses.  Structured errors
    from ``op`` roll back the temporary DB; unexpected exceptions are
    captured and also roll back, so the on-disk DB is never left half-written.

    Consolidating this here means validation (tables, PKs, missing endpoints)
    lives exactly once — in the ``_db.py`` primitive — and the MCP handlers
    stay thin: COW bookkeeping and CSV export, nothing else.
    """
    tmp_path = begin_write(db_path)
    try:
        result = op(tmp_path)
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
# Tool handler functions (extracted for testability)
#
# Embeddings are NOT rebuilt on each upsert: a full model call + HNSW
# drop/recreate per write is wasteful at scale and unnecessary when writes
# come in batches.  The agent runs ``theo_reload`` (or the ``theo reindex``
# CLI) after a batch of edits to refresh the semantic index, mirroring how
# CSVs are flushed once per batch rather than once per row.
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
        allowed = ", ".join(EMBEDDABLE_TABLES)
        return {
            "status": "error",
            "detail": f"Invalid table: {table}. Must be one of {allowed} or null.",
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
        # Structural rebuild succeeded; only embeddings failed.  Surface
        # "partial" (not "ok") so the agent does not assume search is
        # current -- ``reindex_all`` nulls any half-populated column, so
        # search results will be loudly empty rather than silently wrong
        # until the agent retries ``theo_reload`` or runs ``theo reindex``.
        _log.exception("reindex_all failed after rebuild")
        return {
            "status": "partial",
            "rebuilt": True,
            "reindex": {"status": "error", "detail": str(exc)},
            "detail": (
                "Structural rebuild succeeded but embedding reindex failed. "
                "Run 'theo reindex' (or call theo_reload again) to refresh "
                "the semantic index before relying on theo_search."
            ),
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
    """Upsert a node (COW -> export CSV).

    Table / PK / field validation is the responsibility of ``upsert_node`` —
    its structured errors are forwarded verbatim.
    """
    return _run_write(db_path, csv_dir, lambda tmp: upsert_node(tmp, table, properties))


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
    """Upsert a relationship (COW -> export CSV).

    Rel-type and endpoint-existence validation is owned by ``upsert_edge``.
    """
    return _run_write(
        db_path,
        csv_dir,
        lambda tmp: upsert_edge(
            tmp, rel_type, from_id, to_id, description, git_revision=git_revision
        ),
    )


def handle_theo_delete_node(
    db_path: Path,
    csv_dir: Path,
    table: str,
    id: str,
    *,
    detach: bool = False,
) -> dict[str, Any]:
    """Delete a node (COW -> export CSV).

    Table / not-found / referential-integrity errors are produced by
    ``delete_node`` and surfaced unchanged.
    """
    return _run_write(db_path, csv_dir, lambda tmp: delete_node(tmp, table, id, detach=detach))


def handle_theo_delete_edge(
    db_path: Path,
    csv_dir: Path,
    rel_type: str,
    from_id: str,
    to_id: str,
) -> dict[str, Any]:
    """Delete a relationship (COW -> export CSV).

    Rel-type and existence validation is owned by ``delete_edge``.
    """
    return _run_write(db_path, csv_dir, lambda tmp: delete_edge(tmp, rel_type, from_id, to_id))


# ---------------------------------------------------------------------------
# MCP server setup
# ---------------------------------------------------------------------------


def run(project_dir_str: str) -> None:
    """Start the MCP server."""
    from mcp.server.fastmcp import FastMCP

    project = load_project(project_dir_str)
    ensure_db(project)
    db_path = project.db_path
    csv_dir = project.csv_dir
    config_path = project.config_path

    # Pre-warm the embedding model so the first ``theo_search`` call is not
    # blocked ~2 s on cold-start model load.  A failure here (offline, bad
    # proxy, corrupt model cache) leaves the server functional for
    # non-embedding tools -- ``theo_stats`` / ``theo_query`` do not need the
    # model -- so log loudly and continue rather than aborting startup.
    try:
        prewarm_model()
    except Exception:
        _log.exception(
            "Failed to pre-warm embedding model; theo_search will error on invocation",
        )

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

        Note: the ``top_k: int`` annotation is the contract MCP advertises to
        agents, but clients occasionally send strings or floats over the wire.
        ``handle_theo_search`` coerces and clamps ``top_k`` itself, so the
        handler is the source of truth for validation — not this signature.
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

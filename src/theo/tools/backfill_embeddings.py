"""
Backfill embeddings for all existing nodes in the code-intelligence graph.

    backfill_embeddings(db_path, force=False) -> dict

Reads all nodes, computes embeddings for those missing them,
writes embeddings back, and creates HNSW indexes.

Usage: python -m theo.tools.backfill_embeddings <db_path> [--force]
"""

from __future__ import annotations

from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo._shared._ext import collect_rows, execute, get_next_list
from theo._shared._schema import PK_MAP, TABLES
from theo._shared.embed import embed_text
from theo.tools.manage_indexes import create_vector_indexes, drop_vector_indexes

_log = get_logger("backfill_embeddings")

# Text fields to concatenate for each node's embedding input.
_TEXT_FIELDS: list[str] = ["description", "notes"]

# Table -> (primary key field, text fields).  PK is derived from _schema.PK_MAP
# to maintain a single source of truth for primary key field names.
_TABLE_SPECS: dict[str, tuple[str, list[str]]] = {
    table: (PK_MAP[table], _TEXT_FIELDS) for table in TABLES
}


def backfill_embeddings(db_path: str, force: bool = False) -> dict[str, Any]:
    """Compute and store embeddings for all nodes, then build HNSW indexes.

    Args:
        db_path: Path to the KuzuDB database (opened in read-write mode).
        force: If True, re-embed all nodes even if they already have embeddings.

    Returns:
        {"total": N, "embedded": M, "skipped": K, "indexes_created": True}
    """
    # Must drop HNSW indexes before SET operations on the embedding column.
    # KuzuDB does not support SET on columns with active indexes.
    _log.info("[WRITE] Backfill started (force=%s): dropping indexes before write", force)
    drop_vector_indexes(db_path)

    db = lb.Database(db_path)
    conn = lb.Connection(db)

    to_embed = 0
    embedded = 0
    skipped = 0

    for table, (pk_field, text_fields) in _TABLE_SPECS.items():
        # Read all nodes with their text fields and current embedding status.
        field_list = ", ".join(f"n.{f} AS {f}" for f in text_fields)
        null_filter = "" if force else "WHERE n.embedding IS NULL "
        cypher = f"MATCH (n:{table}) {null_filter}RETURN n.{pk_field} AS pk, {field_list}"
        # Collect rows in memory (needed for batch embedding).
        rows = collect_rows(execute(conn, cypher))

        to_embed += len(rows)

        if not rows:
            continue

        # Build texts for batch embedding.
        texts: list[str] = []
        for row in rows:
            parts = [row.get(f) or "" for f in text_fields]
            texts.append("\n\n".join(parts))

        # Compute embeddings in one batch.
        _log.info("[WRITE] Embedding %d nodes for table %s", len(texts), table)
        vectors = embed_text(texts)

        # Write embeddings back via Cypher MERGE.
        for row, vec in zip(rows, vectors, strict=True):
            conn.execute(
                f"MATCH (n:{table} {{{pk_field}: $pk}}) SET n.embedding = $emb",
                {"pk": row["pk"], "emb": vec},
            )
            embedded += 1
        _log.info("[WRITE] Wrote %d embeddings for table %s", len(vectors), table)

    # Count nodes that already had embeddings (only meaningful when not forcing).
    if not force:
        for table, (_pk_field, _) in _TABLE_SPECS.items():
            count_result = execute(
                conn,
                f"MATCH (n:{table}) WHERE n.embedding IS NOT NULL RETURN count(n)",
            )
            if count_result.has_next():
                count_row = get_next_list(count_result)
                skipped += int(count_row[0])
        # The ones we just embedded are counted in both; subtract them.
        skipped -= embedded

    # Explicitly close before building indexes -- create_vector_indexes
    # opens its own connection, and KuzuDB does not support concurrent
    # write handles on the same database file.
    del conn
    db.close()

    # Build HNSW indexes on the now-populated embeddings.
    _log.info("[WRITE] Rebuilding HNSW indexes after backfill")
    idx_result = create_vector_indexes(db_path)
    _log.info(
        "[WRITE] Backfill complete: embedded=%d skipped=%d indexes_ok=%s",
        embedded,
        skipped,
        idx_result["status"] == "ok",
    )

    return {
        "total": to_embed + skipped,
        "embedded": embedded,
        "skipped": skipped,
        "indexes_created": idx_result["status"] == "ok",
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python -m theo.tools.backfill_embeddings <db_path> [--force]",
            file=sys.stderr,
        )
        sys.exit(1)

    db = sys.argv[1]
    force = "--force" in sys.argv
    print(json.dumps(backfill_embeddings(db, force=force), indent=2))

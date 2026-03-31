"""
Manage HNSW vector indexes for semantic search.

    create_vector_indexes(db_path) -> dict
    drop_vector_indexes(db_path) -> dict

Creates or rebuilds HNSW indexes on the embedding column of all node tables.
Uses KuzuDB's native CALL CREATE_VECTOR_INDEX with cosine metric.
Requires the VECTOR extension (installed once, loaded per connection).
"""

from __future__ import annotations

from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo.graph._ext import load_vector_ext

_log = get_logger("manage_indexes")

# Convention: {table_lower}_emb_idx
_INDEX_SPECS: list[tuple[str, str]] = [
    ("Concept", "concept_emb_idx"),
    ("SourceFile", "sourcefile_emb_idx"),
    ("Symbol", "symbol_emb_idx"),
]


def create_vector_indexes(db_path: str) -> dict[str, Any]:
    """Create HNSW indexes on the embedding column of all node tables.

    Idempotent: drops existing indexes before recreating them.
    Opens the database in read-write mode.

    Returns:
        {"status": "ok", "indexes": ["concept_emb_idx", ...]}
    """
    db = lb.Database(db_path)
    conn = lb.Connection(db)
    load_vector_ext(conn)

    created: list[str] = []
    for table, idx_name in _INDEX_SPECS:
        # Drop if it already exists (CREATE is not idempotent in KuzuDB).
        try:
            conn.execute(f"CALL DROP_VECTOR_INDEX('{table}', '{idx_name}')")
            _log.info(
                "[WRITE] Dropped existing index %s on %s before recreate",
                idx_name,
                table,
            )
        except RuntimeError as e:
            if "doesn't have an index" not in str(e):
                raise
        _log.info("[WRITE] Creating HNSW index %s on %s", idx_name, table)
        conn.execute(
            f"CALL CREATE_VECTOR_INDEX('{table}', '{idx_name}', 'embedding', metric := 'cosine')"
        )
        created.append(idx_name)

    del conn
    db.close()
    _log.info("[WRITE] Created %d HNSW indexes: %s", len(created), created)
    return {"status": "ok", "indexes": created}


def drop_vector_indexes(db_path: str) -> dict[str, Any]:
    """Drop all HNSW vector indexes.

    Idempotent: silently skips indexes that do not exist.
    Opens the database in read-write mode.

    Returns:
        {"status": "ok", "dropped": ["concept_emb_idx", ...]}
    """
    db = lb.Database(db_path)
    conn = lb.Connection(db)
    load_vector_ext(conn)

    dropped: list[str] = []
    for table, idx_name in _INDEX_SPECS:
        try:
            conn.execute(f"CALL DROP_VECTOR_INDEX('{table}', '{idx_name}')")
            dropped.append(idx_name)
            _log.info("[WRITE] Dropped index %s on %s", idx_name, table)
        except RuntimeError as e:
            if "doesn't have an index" not in str(e):
                raise

    del conn
    db.close()
    if dropped:
        _log.info("[WRITE] Dropped %d HNSW indexes: %s", len(dropped), dropped)
    return {"status": "ok", "dropped": dropped}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: manage_indexes.py <db_path> [create|drop]", file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else "create"

    if action == "create":
        print(json.dumps(create_vector_indexes(db_path), indent=2))
    elif action == "drop":
        print(json.dumps(drop_vector_indexes(db_path), indent=2))
    else:
        print(f"Unknown action: {action}. Use 'create' or 'drop'.", file=sys.stderr)
        sys.exit(1)

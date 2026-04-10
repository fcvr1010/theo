"""
Semantic search over the code-intelligence graph.

    semantic_search(db_path, query, table=None, top_k=10, expand=False) -> dict

query: Natural language question (e.g., "how are messages delivered?")
table: Optional filter -- "Concept", "SourceFile", or None for all.
top_k: Number of results to return.
expand: If True, follow graph edges from matched nodes to get neighbourhood context.

Returns:
  {
    "matches": [...],              # Top-K semantic matches with scores
    "related_concepts": [...],     # (only if expand=True)
    "related_files": [...]         # (only if expand=True)
  }
"""

from __future__ import annotations

from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo._embed import embed_query
from theo._ext import collect_rows, execute, get_next_list, load_vector_ext
from theo._schema import EMBEDDING_DIM, INDEX_MAP, PK_MAP, TABLES

_log = get_logger("semantic_search")

_MAX_NOTES_LEN = 200


def _truncate(text: str | None, max_len: int = _MAX_NOTES_LEN) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _hnsw_search(
    conn: lb.Connection,
    table: str,
    query_vec: list[float],
    top_k: int,
) -> list[dict[str, Any]] | None:
    """Try HNSW search on a single table.  Returns None if no index exists."""
    idx_name = INDEX_MAP[table]
    pk_field = PK_MAP[table]
    try:
        result = execute(
            conn,
            f"CALL QUERY_VECTOR_INDEX('{table}', '{idx_name}', $qvec, {top_k}) "
            f"RETURN node.{pk_field} AS pk, node.name AS name, "
            f"node.description AS description, node.notes AS notes, distance",
            {"qvec": query_vec},
        )
    except RuntimeError as e:
        if "doesn't have an index" in str(e):
            return None
        raise

    cols: list[str] = result.get_column_names()
    matches: list[dict[str, Any]] = []
    while result.has_next():
        row = dict(zip(cols, get_next_list(result), strict=True))
        matches.append(
            {
                "table": table,
                "id": row["pk"],
                "name": row["name"],
                "description": row["description"] or "",
                "notes": _truncate(row["notes"]),
                "score": 1.0 - row["distance"],
            }
        )
    return matches


def _brute_force_search(
    conn: lb.Connection,
    table: str,
    query_vec: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    """Brute-force cosine similarity search on a single table."""
    pk_field = PK_MAP[table]
    result = execute(
        conn,
        f"MATCH (n:{table}) "
        f"WHERE n.embedding IS NOT NULL "
        f"WITH n, array_cosine_similarity(n.embedding, "
        f'cast($qvec, "FLOAT[{EMBEDDING_DIM}]")) AS sim '
        f"RETURN n.{pk_field} AS pk, n.name AS name, "
        f"n.description AS description, n.notes AS notes, sim "
        f"ORDER BY sim DESC LIMIT {top_k}",
        {"qvec": query_vec},
    )
    cols: list[str] = result.get_column_names()
    matches: list[dict[str, Any]] = []
    while result.has_next():
        row = dict(zip(cols, get_next_list(result), strict=True))
        matches.append(
            {
                "table": table,
                "id": row["pk"],
                "name": row["name"],
                "description": row["description"] or "",
                "notes": _truncate(row["notes"]),
                "score": row["sim"],
            }
        )
    return matches


def _search_table(
    conn: lb.Connection,
    table: str,
    query_vec: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    """Search a table, trying HNSW first with brute-force fallback."""
    hnsw_results = _hnsw_search(conn, table, query_vec, top_k)
    if hnsw_results is not None:
        return hnsw_results
    return _brute_force_search(conn, table, query_vec, top_k)


def _expand_matches(
    conn: lb.Connection,
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Follow graph edges from matched nodes to build neighbourhood context.

    Expands both Concept and SourceFile matches:
    - Concept matches: follow DependsOn, InteractsWith (both directions),
      and find files via BelongsTo.
    - SourceFile matches: follow BelongsTo to find parent concepts,
      and Imports (both directions) to find related files.
    """
    matched_concept_ids: set[str] = set()
    matched_file_paths: set[str] = set()

    for m in matches:
        if m["table"] == "Concept":
            matched_concept_ids.add(m["id"])
        elif m["table"] == "SourceFile":
            matched_file_paths.add(m["id"])

    related_concepts: dict[str, dict[str, Any]] = {}
    related_files: dict[str, dict[str, Any]] = {}

    # --- Expand from Concept matches ---
    if matched_concept_ids:
        id_list = list(matched_concept_ids)

        # DependsOn and InteractsWith (both directions).
        for rel in ("DependsOn", "InteractsWith"):
            for row in collect_rows(
                execute(
                    conn,
                    f"MATCH (a:Concept)-[:{rel}]->(b:Concept) "
                    f"WHERE a.id IN $ids "
                    f"RETURN b.id AS id, b.name AS name, b.description AS description",
                    {"ids": id_list},
                )
            ):
                if row["id"] not in matched_concept_ids:
                    related_concepts[row["id"]] = {
                        "id": row["id"],
                        "name": row["name"],
                        "description": row["description"] or "",
                    }

            for row in collect_rows(
                execute(
                    conn,
                    f"MATCH (a:Concept)-[:{rel}]->(b:Concept) "
                    f"WHERE b.id IN $ids "
                    f"RETURN a.id AS id, a.name AS name, a.description AS description",
                    {"ids": id_list},
                )
            ):
                if row["id"] not in matched_concept_ids:
                    related_concepts[row["id"]] = {
                        "id": row["id"],
                        "name": row["name"],
                        "description": row["description"] or "",
                    }

        # Files belonging to matched concepts (incoming BelongsTo).
        for row in collect_rows(
            execute(
                conn,
                "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept) "
                "WHERE c.id IN $ids "
                "RETURN f.path AS path, f.name AS name, f.description AS description",
                {"ids": id_list},
            )
        ):
            if row["path"] not in matched_file_paths:
                related_files[row["path"]] = {
                    "path": row["path"],
                    "name": row["name"],
                    "description": row["description"] or "",
                }

    # --- Expand from SourceFile matches ---
    if matched_file_paths:
        path_list = list(matched_file_paths)

        # Concepts that matched files belong to (outgoing BelongsTo).
        for row in collect_rows(
            execute(
                conn,
                "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept) "
                "WHERE f.path IN $paths "
                "RETURN c.id AS id, c.name AS name, c.description AS description",
                {"paths": path_list},
            )
        ):
            if row["id"] not in matched_concept_ids:
                related_concepts[row["id"]] = {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"] or "",
                }

        # Files connected via Imports (both directions).
        for row in collect_rows(
            execute(
                conn,
                "MATCH (a:SourceFile)-[:Imports]->(b:SourceFile) "
                "WHERE a.path IN $paths "
                "RETURN b.path AS path, b.name AS name, b.description AS description",
                {"paths": path_list},
            )
        ):
            if row["path"] not in matched_file_paths:
                related_files[row["path"]] = {
                    "path": row["path"],
                    "name": row["name"],
                    "description": row["description"] or "",
                }

        for row in collect_rows(
            execute(
                conn,
                "MATCH (a:SourceFile)-[:Imports]->(b:SourceFile) "
                "WHERE b.path IN $paths "
                "RETURN a.path AS path, a.name AS name, a.description AS description",
                {"paths": path_list},
            )
        ):
            if row["path"] not in matched_file_paths:
                related_files[row["path"]] = {
                    "path": row["path"],
                    "name": row["name"],
                    "description": row["description"] or "",
                }

    return {
        "related_concepts": list(related_concepts.values()),
        "related_files": list(related_files.values()),
    }


def semantic_search(
    db_path: str,
    query: str,
    table: str | None = None,
    top_k: int = 10,
    expand: bool = False,
) -> dict[str, Any]:
    """Run semantic search over the code-intelligence graph.

    Args:
        db_path: Path to the KuzuDB database directory.
        query: Natural language search query.
        table: Optional table filter ("Concept", "SourceFile").
        top_k: Number of results to return.
        expand: If True, follow graph edges to add neighbourhood context.

    Returns:
        Dict with "matches" (always) and "related_*" keys (when expand=True).
    """
    if table and table not in TABLES:
        raise ValueError(f"Invalid table: {table!r}. Must be one of {TABLES}")

    _log.info(
        '[READ] Semantic search on %s: query="%s" table=%s top_k=%d expand=%s',
        db_path,
        query[:200],
        table or "all",
        top_k,
        expand,
    )

    db = lb.Database(db_path, read_only=True)
    conn = lb.Connection(db)
    load_vector_ext(conn)

    query_vec = embed_query(query)

    tables = [table] if table else list(TABLES)
    all_matches: list[dict[str, Any]] = []
    for tbl in tables:
        all_matches.extend(_search_table(conn, tbl, query_vec, top_k))

    # Sort by score descending, take top-K across all tables.
    all_matches.sort(key=lambda m: m["score"], reverse=True)
    matches = all_matches[:top_k]

    _log.info("[READ] Semantic search returned %d matches", len(matches))

    result: dict[str, Any] = {"matches": matches}

    if expand and matches:
        expansion = _expand_matches(conn, matches)
        result.update(expansion)

    del conn
    db.close()

    return result


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: semantic_search.py <db_path> <query> [table] [top_k] [expand]",
            file=sys.stderr,
        )
        sys.exit(1)

    db_path = sys.argv[1]
    q = sys.argv[2]
    tbl = sys.argv[3] if len(sys.argv) > 3 else None
    k = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    exp = sys.argv[5].lower() in ("true", "1", "yes") if len(sys.argv) > 5 else False

    output = semantic_search(db_path, q, table=tbl, top_k=k, expand=exp)
    print(json.dumps(output, indent=2))

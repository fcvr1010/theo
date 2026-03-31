"""
Semantic search over the code-intelligence graph.

    semantic_search(db_path, query, table=None, top_k=10, expand=False) -> dict

query: Natural language question (e.g., "how are messages delivered?")
table: Optional filter -- "Concept", "SourceFile", "Symbol", or None for all.
top_k: Number of results to return.
expand: If True, follow graph edges from matched nodes to get neighbourhood context.

Returns:
  {
    "matches": [...],              # Top-K semantic matches with scores
    "related_concepts": [...],     # (only if expand=True)
    "related_files": [...],        # (only if expand=True)
    "related_symbols": [...]       # (only if expand=True)
  }
"""

from __future__ import annotations

from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo.graph._ext import execute, load_vector_ext
from theo.graph._schema import PK_MAP, TABLES
from theo.graph.embed_text import EMBEDDING_DIM, embed_query

_log = get_logger("semantic_search")

# HNSW index names (must match manage_indexes.py convention).
_INDEX_MAP = {
    "Concept": "concept_emb_idx",
    "SourceFile": "sourcefile_emb_idx",
    "Symbol": "symbol_emb_idx",
}

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
    idx_name = _INDEX_MAP[table]
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
        row = dict(zip(cols, result.get_next(), strict=True))
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
        row = dict(zip(cols, result.get_next(), strict=True))
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


def _collect_rows(result: lb.QueryResult) -> list[dict[str, Any]]:
    """Drain a KuzuDB query result into a list of dicts."""
    cols: list[str] = result.get_column_names()
    rows: list[dict[str, Any]] = []
    while result.has_next():
        rows.append(dict(zip(cols, result.get_next(), strict=True)))
    return rows


def _expand_matches(
    conn: lb.Connection,
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Follow graph edges from matched nodes to build neighbourhood context.

    Uses batched queries (WHERE id IN $ids) instead of per-node loops to
    reduce the number of round-trips from O(5*N) to O(5).
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
    related_symbols: dict[str, dict[str, Any]] = {}

    if matched_concept_ids:
        id_list = list(matched_concept_ids)

        # Expand concepts: DependsOn and InteractsWith (both directions).
        for rel in ("DependsOn", "InteractsWith"):
            # Outgoing edges.
            for row in _collect_rows(
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

            # Incoming edges.
            for row in _collect_rows(
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
        for row in _collect_rows(
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

    # Symbols defined in matched or related files (batched DefinedIn).
    all_file_paths = list(matched_file_paths | set(related_files.keys()))
    if all_file_paths:
        for row in _collect_rows(
            execute(
                conn,
                "MATCH (s:Symbol)-[:DefinedIn]->(f:SourceFile) "
                "WHERE f.path IN $paths "
                "RETURN s.id AS id, s.name AS name, s.description AS description",
                {"paths": all_file_paths},
            )
        ):
            related_symbols[row["id"]] = {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"] or "",
            }

    return {
        "related_concepts": list(related_concepts.values()),
        "related_files": list(related_files.values()),
        "related_symbols": list(related_symbols.values()),
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
        db_path: Path to the KuzuDB database.
        query: Natural language search query.
        table: Optional table filter ("Concept", "SourceFile", "Symbol").
        top_k: Number of results to return.
        expand: If True, follow graph edges to add neighbourhood context.

    Returns:
        Dict with "matches" (always) and "related_*" keys (when expand=True).
    """
    if table and table not in TABLES:
        raise ValueError(f"Invalid table: {table!r}. Must be one of {TABLES}")

    _log.info(
        '[READ] Semantic search: query="%s" table=%s top_k=%d expand=%s',
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

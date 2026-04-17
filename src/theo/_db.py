"""KuzuDB operations for the Theo knowledge graph.

All functions accept a ``db_path`` and open a fresh connection per call.
This keeps the API stateless and COW-friendly (the caller may pass either
the real path or a temporary copy).
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import real_ladybug as lb

from theo._ext import load_vector_ext
from theo._schema import (
    CSV_FILES,
    EMBEDDABLE_TABLES,
    EMBEDDING_DIM,
    FIELD_MAP,
    HNSW_INDEX_NAMES,
    NODE_COLUMNS,
    NODE_DDL,
    NODE_TABLES,
    PK_MAP,
    REL_DDL,
    REL_ENDPOINTS,
    REL_TABLES,
)


@contextlib.contextmanager
def _opened(db_path: Path, *, read_only: bool = False) -> Iterator[lb.Connection]:
    """Open a KuzuDB connection, yield it, and reliably close on exit.

    KuzuDB holds a WAL per writer handle; leaving handles for CPython GC to
    close has been observed to corrupt the WAL on rapid-fire writes.  The
    context manager closes the connection + database deterministically and
    avoids relying on refcount-driven ``__del__``.

    The VECTOR extension is loaded on every connection (idempotent, cheap)
    because any write to a table that carries an active HNSW index --
    including plain ``MERGE``/``SET`` on non-embedding columns -- requires
    the extension loaded on the writing connection.  Loading universally
    avoids latent "extension is not loaded" errors after a reindex.
    """
    db = lb.Database(str(db_path), read_only=read_only)
    conn = lb.Connection(db)
    try:
        load_vector_ext(conn)
        yield conn
    finally:
        # Drop the Python-side connection before closing the Database so the
        # native side releases the WAL cleanly.
        del conn
        db.close()


def _execute(
    conn: lb.Connection,
    query: str,
    params: dict[str, Any] | None = None,
) -> lb.QueryResult:
    """Execute a Cypher query and return a single ``QueryResult``.

    ``Connection.execute`` is typed as returning ``QueryResult | list[QueryResult]``.
    All Theo queries are single statements, so we narrow the type here.
    """
    result = conn.execute(query, params)
    return cast(lb.QueryResult, result)


def _scalar(result: lb.QueryResult) -> Any:
    """Extract a single scalar value from a query result."""
    row = result.get_next()
    return row[0] if isinstance(row, list) else next(iter(row.values()))


def _row(result: lb.QueryResult) -> list[Any]:
    """Fetch the next row as a list (narrows the stub-level list|dict union)."""
    row = result.get_next()
    return cast(list[Any], row)


def init_schema(db_path: Path) -> None:
    """Create all node and relationship tables in a new KuzuDB database."""
    with _opened(db_path) as conn:
        for ddl in NODE_DDL.values():
            _execute(conn, ddl)
        for ddl in REL_DDL.values():
            _execute(conn, ddl)


# Sentinel substrings used to detect benign "already-present" / "absent"
# states in KuzuDB/LadybugDB RuntimeError messages.  These are coupled to the
# pinned ladybug version (pyproject.toml).  If a ladybug upgrade changes the
# wording, the integration tests that exercise these branches will start
# failing — update the sentinels then.
_ERR_COL_PRESENT = ("already has property", "already exists")
_ERR_INDEX_ABSENT = ("doesn't have an index",)


def migrate_embedding_column(db_path: Path) -> None:
    """Ensure every EMBEDDABLE_TABLES entry has an ``embedding FLOAT[N]`` column.

    Idempotent: re-runs safely on DBs where the column already exists.  Any
    RuntimeError that is not the specific "column already present" signal is
    re-raised so upstream problems are surfaced, not masked.
    """
    with _opened(db_path) as conn:
        for table in EMBEDDABLE_TABLES:
            try:
                _execute(conn, f"ALTER TABLE {table} ADD embedding FLOAT[{EMBEDDING_DIM}]")
            except RuntimeError as exc:
                if not any(s in str(exc) for s in _ERR_COL_PRESENT):
                    raise


# ---------------------------------------------------------------------------
# Vector index lifecycle (node tables only)
#
# KuzuDB's HNSW index supports only node tables, so relationship embeddings
# are always searched via brute-force ``array_cosine_similarity``.  For node
# tables KuzuDB disallows ``SET`` on a column with an active HNSW index, so
# every embedding write must drop the index first and recreate it afterwards.
# On graphs of ~50-500 nodes the rebuild is sub-second; heavier workloads can
# batch writes via ``reindex_all`` which drops the index once up front.
# ---------------------------------------------------------------------------


def _drop_vector_index(conn: lb.Connection, table: str) -> bool:
    """Drop ``table``'s HNSW index if present.  Returns True iff a drop ran.

    Swallows only the specific "index absent" wording so other RuntimeErrors
    (e.g. extension-load failures) are not silently masked.
    """
    idx_name = HNSW_INDEX_NAMES[table]
    try:
        _execute(conn, f"CALL DROP_VECTOR_INDEX('{table}', '{idx_name}')")
    except RuntimeError as exc:
        if not any(s in str(exc) for s in _ERR_INDEX_ABSENT):
            raise
        return False
    return True


def _create_vector_index(conn: lb.Connection, table: str) -> None:
    """Create a fresh HNSW index on ``table.embedding`` with cosine metric.

    The index is dropped first if it already exists (CREATE is not idempotent
    in KuzuDB).
    """
    _drop_vector_index(conn, table)
    idx_name = HNSW_INDEX_NAMES[table]
    _execute(
        conn,
        f"CALL CREATE_VECTOR_INDEX('{table}', '{idx_name}', 'embedding', metric := 'cosine')",
    )


def create_vector_index(db_path: Path, table: str) -> None:
    """Public wrapper: create/recreate the HNSW index for a single node table."""
    if table not in HNSW_INDEX_NAMES:
        raise ValueError(f"HNSW indexes are only supported on node tables: {table}")
    with _opened(db_path) as conn:
        _create_vector_index(conn, table)


def drop_vector_index(db_path: Path, table: str) -> bool:
    """Public wrapper: drop the HNSW index for a single node table."""
    if table not in HNSW_INDEX_NAMES:
        raise ValueError(f"HNSW indexes are only supported on node tables: {table}")
    with _opened(db_path) as conn:
        return _drop_vector_index(conn, table)


def create_all_vector_indexes(db_path: Path) -> list[str]:
    """Create HNSW indexes on every node table that carries embeddings."""
    with _opened(db_path) as conn:
        for table in HNSW_INDEX_NAMES:
            _create_vector_index(conn, table)
    return list(HNSW_INDEX_NAMES)


def drop_all_vector_indexes(db_path: Path) -> list[str]:
    """Drop HNSW indexes on every node table that carries them."""
    dropped: list[str] = []
    with _opened(db_path) as conn:
        for table in HNSW_INDEX_NAMES:
            if _drop_vector_index(conn, table):
                dropped.append(table)
    return dropped


def write_node_embedding(
    db_path: Path,
    table: str,
    pk_value: str,
    vector: list[float],
) -> None:
    """Store ``vector`` on a single node and rebuild that table's HNSW index.

    Sequence: drop-index → SET embedding → create-index.  A no-op when
    ``vector`` is empty (caller should skip empty-text rows upstream).

    The recreate step runs inside a ``try/finally``: a Python-level exception
    during SET still rebuilds the HNSW so the table is not left unindexed.
    (A hard process crash between DROP and CREATE can still leave it
    dropped; search falls back to brute force and the next successful
    write recreates the index.)
    """
    if table not in NODE_TABLES:
        raise ValueError(f"Unknown node table: {table}")
    if not vector:
        return
    pk_field = PK_MAP[table]
    with _opened(db_path) as conn:
        _drop_vector_index(conn, table)
        try:
            _execute(
                conn,
                f"MATCH (n:{table} {{{pk_field}: $pk}}) SET n.embedding = $emb",
                {"pk": pk_value, "emb": vector},
            )
        finally:
            _create_vector_index(conn, table)


def write_edge_embedding(
    db_path: Path,
    rel_type: str,
    from_id: str,
    to_id: str,
    vector: list[float],
) -> None:
    """Store ``vector`` on a single relationship.

    Relationship tables have no HNSW index in KuzuDB, so this is a plain
    ``SET``.  Search over relationship embeddings uses brute-force cosine
    similarity.
    """
    if rel_type not in REL_TABLES:
        raise ValueError(f"Unknown relationship type: {rel_type}")
    if not vector:
        return
    from_table, to_table = REL_ENDPOINTS[rel_type]
    from_pk = PK_MAP[from_table]
    to_pk = PK_MAP[to_table]
    with _opened(db_path) as conn:
        _execute(
            conn,
            f"MATCH (a:{from_table} {{{from_pk}: $from_id}})"
            f"-[r:{rel_type}]->"
            f"(b:{to_table} {{{to_pk}: $to_id}}) "
            "SET r.embedding = $emb",
            {"from_id": from_id, "to_id": to_id, "emb": vector},
        )


# ---------------------------------------------------------------------------
# Semantic search + bulk reindex
# ---------------------------------------------------------------------------


def _hnsw_search_node(
    conn: lb.Connection, table: str, query_vec: list[float], top_k: int
) -> list[dict[str, Any]] | None:
    """Run HNSW search on a node table.  Returns None if the index is absent.

    Extension-load failures and other RuntimeErrors propagate — only the
    specific "index absent" wording signals a legitimate fallback to
    brute-force search.
    """
    idx_name = HNSW_INDEX_NAMES[table]
    pk_field = PK_MAP[table]
    try:
        result = _execute(
            conn,
            f"CALL QUERY_VECTOR_INDEX('{table}', '{idx_name}', $qvec, {top_k}) "
            f"RETURN node.{pk_field} AS id, node.name AS name, "
            f"node.description AS description, distance",
            {"qvec": query_vec},
        )
    except RuntimeError as exc:
        if any(s in str(exc) for s in _ERR_INDEX_ABSENT):
            return None
        raise
    matches: list[dict[str, Any]] = []
    while result.has_next():
        row = _row(result)
        matches.append(
            {
                "kind": "node",
                "table": table,
                "score": 1.0 - row[3],
                "description": row[2] or "",
                "ref": {"id": row[0], "name": row[1]},
            }
        )
    return matches


def _brute_force_search_node(
    conn: lb.Connection, table: str, query_vec: list[float], top_k: int
) -> list[dict[str, Any]]:
    """Brute-force cosine search on a node table."""
    pk_field = PK_MAP[table]
    result = _execute(
        conn,
        f"MATCH (n:{table}) WHERE n.embedding IS NOT NULL "
        f"WITH n, array_cosine_similarity(n.embedding, "
        f'cast($qvec, "FLOAT[{EMBEDDING_DIM}]")) AS sim '
        f"RETURN n.{pk_field} AS id, n.name AS name, "
        f"n.description AS description, sim "
        f"ORDER BY sim DESC LIMIT {top_k}",
        {"qvec": query_vec},
    )
    matches: list[dict[str, Any]] = []
    while result.has_next():
        row = _row(result)
        matches.append(
            {
                "kind": "node",
                "table": table,
                "score": row[3],
                "description": row[2] or "",
                "ref": {"id": row[0], "name": row[1]},
            }
        )
    return matches


def _brute_force_search_edge(
    conn: lb.Connection, rel_type: str, query_vec: list[float], top_k: int
) -> list[dict[str, Any]]:
    """Brute-force cosine search on a relationship table."""
    from_table, to_table = REL_ENDPOINTS[rel_type]
    from_pk = PK_MAP[from_table]
    to_pk = PK_MAP[to_table]
    result = _execute(
        conn,
        f"MATCH (a:{from_table})-[r:{rel_type}]->(b:{to_table}) "
        f"WHERE r.embedding IS NOT NULL "
        f"WITH a, r, b, array_cosine_similarity(r.embedding, "
        f'cast($qvec, "FLOAT[{EMBEDDING_DIM}]")) AS sim '
        f"RETURN a.{from_pk} AS from_id, b.{to_pk} AS to_id, "
        f"r.description AS description, sim "
        f"ORDER BY sim DESC LIMIT {top_k}",
        {"qvec": query_vec},
    )
    matches: list[dict[str, Any]] = []
    while result.has_next():
        row = _row(result)
        matches.append(
            {
                "kind": "edge",
                "rel_type": rel_type,
                "score": row[3],
                "description": row[2] or "",
                "ref": {"from_id": row[0], "to_id": row[1]},
            }
        )
    return matches


def semantic_search(
    db_path: Path,
    query_vec: list[float],
    table: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """Search for nodes / edges semantically closest to ``query_vec``.

    ``table=None`` searches every embeddable table; otherwise restricts to
    one node or relationship table.  Node tables use HNSW when the index
    exists and fall back to brute-force cosine similarity; relationship
    tables always use brute force (KuzuDB's HNSW does not support REL).

    Returns a list sorted by descending score, sliced to ``top_k`` globally.
    Each match has a uniform shape::

        {
            "kind": "node" | "edge",
            "table": <node table> | "rel_type": <rel table>,
            "score": float,
            "description": str,
            "ref": {"id": str, "name": str}                   # kind == "node"
                 | {"from_id": str, "to_id": str}              # kind == "edge"
        }
    """
    if table is not None and table not in EMBEDDABLE_TABLES:
        raise ValueError(f"Unknown embeddable table: {table}")

    targets = [table] if table else list(EMBEDDABLE_TABLES)
    collected: list[dict[str, Any]] = []
    with _opened(db_path, read_only=True) as conn:
        for tbl in targets:
            if tbl in NODE_TABLES:
                hnsw = _hnsw_search_node(conn, tbl, query_vec, top_k)
                collected.extend(
                    hnsw
                    if hnsw is not None
                    else _brute_force_search_node(conn, tbl, query_vec, top_k)
                )
            else:
                collected.extend(_brute_force_search_edge(conn, tbl, query_vec, top_k))

    collected.sort(key=lambda m: m["score"], reverse=True)
    return collected[:top_k]


def reindex_all(db_path: Path) -> dict[str, int]:
    """Recompute embeddings for every node and relationship.

    Three phases to minimise writer-handle hold time:

    1. **Read** (read-only conn): collect ``(pk, text)`` pairs from every
       embeddable table.
    2. **Embed** (no DB handle): run fastembed on all collected texts.
    3. **Write** (writer conn): for each node table run drop-SET-create;
       for each rel table just SET.

    Returns per-table counts of rows that received a fresh embedding.  The
    caller is responsible for checking :func:`theo._embed.is_available`
    before invoking this function.
    """
    from theo._embed import embed_documents, make_edge_text, make_node_text

    # Phase 1: collect text under a read-only handle.
    node_rows: dict[str, list[tuple[Any, str]]] = {}
    edge_rows: dict[str, list[tuple[Any, Any, str]]] = {}
    with _opened(db_path, read_only=True) as conn:
        for table in NODE_TABLES:
            pk_field = PK_MAP[table]
            result = _execute(
                conn,
                f"MATCH (n:{table}) RETURN n.{pk_field} AS pk, "
                f"n.description AS description, n.notes AS notes",
            )
            rows: list[tuple[Any, str]] = []
            while result.has_next():
                row = _row(result)
                text = make_node_text(row[1], row[2])
                if text:
                    rows.append((row[0], text))
            node_rows[table] = rows

        for rel_type in REL_TABLES:
            from_table, to_table = REL_ENDPOINTS[rel_type]
            from_pk = PK_MAP[from_table]
            to_pk = PK_MAP[to_table]
            result = _execute(
                conn,
                f"MATCH (a:{from_table})-[r:{rel_type}]->(b:{to_table}) "
                f"RETURN a.{from_pk} AS from_id, b.{to_pk} AS to_id, "
                f"r.description AS description",
            )
            rels: list[tuple[Any, Any, str]] = []
            while result.has_next():
                row = _row(result)
                text = make_edge_text(row[2])
                if text:
                    rels.append((row[0], row[1], text))
            edge_rows[rel_type] = rels

    # Phase 2: embed outside any DB handle so concurrent readers aren't
    # blocked during the (potentially multi-second) fastembed pass.
    node_vectors: dict[str, list[list[float]]] = {}
    for table, rows in node_rows.items():
        node_vectors[table] = embed_documents([t for _pk, t in rows]) if rows else []
    edge_vectors: dict[str, list[list[float]]] = {}
    for rel_type, rels in edge_rows.items():
        edge_vectors[rel_type] = embed_documents([t for _f, _t, t in rels]) if rels else []

    # Phase 3: single writer connection, drop-SET-create per node table.
    counts: dict[str, int] = {}
    with _opened(db_path) as conn:
        for table in NODE_TABLES:
            rows = node_rows[table]
            vectors = node_vectors[table]
            pk_field = PK_MAP[table]
            _drop_vector_index(conn, table)
            try:
                for (pk_value, _text), vec in zip(rows, vectors, strict=True):
                    _execute(
                        conn,
                        f"MATCH (n:{table} {{{pk_field}: $pk}}) SET n.embedding = $emb",
                        {"pk": pk_value, "emb": vec},
                    )
            finally:
                # Always recreate the index, even if SET raised partway through;
                # otherwise the table would be left indexless until the next
                # reindex.  Search still works via brute-force fallback in the
                # degraded window.
                _create_vector_index(conn, table)
            counts[table] = len(rows)

        for rel_type in REL_TABLES:
            rels = edge_rows[rel_type]
            vectors = edge_vectors[rel_type]
            from_table, to_table = REL_ENDPOINTS[rel_type]
            from_pk = PK_MAP[from_table]
            to_pk = PK_MAP[to_table]
            for (f_id, t_id, _text), vec in zip(rels, vectors, strict=True):
                _execute(
                    conn,
                    f"MATCH (a:{from_table} {{{from_pk}: $from_id}})"
                    f"-[r:{rel_type}]->"
                    f"(b:{to_table} {{{to_pk}: $to_id}}) "
                    "SET r.embedding = $emb",
                    {"from_id": f_id, "to_id": t_id, "emb": vec},
                )
            counts[rel_type] = len(rels)

    return counts


def upsert_node(
    db_path: Path,
    table: str,
    properties: dict[str, Any],
) -> dict[str, Any]:
    """MERGE a node using KuzuDB MERGE + SET pattern.

    Returns ``{"status": "ok", "table": table, "id": pk_value}`` on success,
    or ``{"status": "error", "detail": "..."}`` on failure.
    """
    if table not in PK_MAP:
        return {"status": "error", "detail": f"Unknown node table: {table}"}

    pk_field = PK_MAP[table]
    if pk_field not in properties:
        return {"status": "error", "detail": f"Missing primary key '{pk_field}'"}

    allowed = FIELD_MAP[table]
    extra = set(properties) - allowed
    if extra:
        return {"status": "error", "detail": f"Unknown fields: {extra}"}

    pk_value = properties[pk_field]
    set_fields = {k: v for k, v in properties.items() if k != pk_field}

    if set_fields:
        set_clause = ", ".join(f"n.{k} = ${k}" for k in set_fields)
        cypher = f"MERGE (n:{table} {{{pk_field}: ${pk_field}}}) SET {set_clause}"
    else:
        cypher = f"MERGE (n:{table} {{{pk_field}: ${pk_field}}})"

    params: dict[str, Any] = {pk_field: pk_value, **set_fields}
    with _opened(db_path) as conn:
        _execute(conn, cypher, params)
    return {"status": "ok", "table": table, "id": pk_value}


def upsert_edge(
    db_path: Path,
    rel_type: str,
    from_id: str,
    to_id: str,
    description: str | None = None,
    *,
    git_revision: str,
) -> dict[str, Any]:
    """MERGE a relationship.

    Returns ``{"status": "error", "detail": "..."}`` if endpoint nodes are
    not found in the database.
    """
    if rel_type not in REL_ENDPOINTS:
        return {"status": "error", "detail": f"Unknown relationship type: {rel_type}"}

    from_table, to_table = REL_ENDPOINTS[rel_type]
    from_pk = PK_MAP[from_table]
    to_pk = PK_MAP[to_table]

    with _opened(db_path) as conn:
        # Verify endpoint nodes exist
        from_check = _execute(
            conn,
            f"MATCH (n:{from_table} {{{from_pk}: $pk}}) RETURN count(n)",
            {"pk": from_id},
        )
        if from_check.has_next() and _scalar(from_check) == 0:
            return {"status": "error", "detail": f"{from_table} node '{from_id}' not found"}

        to_check = _execute(
            conn,
            f"MATCH (n:{to_table} {{{to_pk}: $pk}}) RETURN count(n)",
            {"pk": to_id},
        )
        if to_check.has_next() and _scalar(to_check) == 0:
            return {"status": "error", "detail": f"{to_table} node '{to_id}' not found"}

        # MERGE the relationship (two steps: KuzuDB does not support parameter
        # binding in SET clauses combined with MERGE in a single statement)
        merge_cypher = (
            f"MATCH (a:{from_table} {{{from_pk}: $from_id}}), "
            f"(b:{to_table} {{{to_pk}: $to_id}}) "
            f"MERGE (a)-[r:{rel_type}]->(b)"
        )
        _execute(conn, merge_cypher, {"from_id": from_id, "to_id": to_id})

        if description is not None:
            set_cypher = (
                f"MATCH (a:{from_table} {{{from_pk}: $from_id}})"
                f"-[r:{rel_type}]->"
                f"(b:{to_table} {{{to_pk}: $to_id}}) "
                f"SET r.description = $description"
            )
            _execute(
                conn,
                set_cypher,
                {"from_id": from_id, "to_id": to_id, "description": description},
            )

        set_cypher = (
            f"MATCH (a:{from_table} {{{from_pk}: $from_id}})"
            f"-[r:{rel_type}]->"
            f"(b:{to_table} {{{to_pk}: $to_id}}) "
            f"SET r.git_revision = $git_revision"
        )
        _execute(
            conn,
            set_cypher,
            {"from_id": from_id, "to_id": to_id, "git_revision": git_revision},
        )

    return {"status": "ok", "rel_type": rel_type, "from": from_id, "to": to_id}


def delete_node(
    db_path: Path,
    table: str,
    id: str,
    *,
    detach: bool = False,
) -> dict[str, Any]:
    """Delete a node.

    Refuses (returns ``{"status": "error", ...}``) if:
    - the table is unknown,
    - the node does not exist,
    - the node is a ``Concept`` with child ``Concept``s (via ``PartOf``) or
      owning ``SourceFile``s (via ``BelongsTo``); the caller must re-parent
      first to avoid orphans,
    - the node has other incident edges and ``detach`` is ``False``.
    """
    if table not in PK_MAP:
        return {"status": "error", "detail": f"Unknown node table: {table}"}

    pk_field = PK_MAP[table]
    with _opened(db_path) as conn:
        exists = _execute(
            conn,
            f"MATCH (n:{table} {{{pk_field}: $pk}}) RETURN count(n)",
            {"pk": id},
        )
        if _scalar(exists) == 0:
            return {"status": "error", "detail": f"{table} node '{id}' not found"}

        # Orphaning guardrail: Concepts with children cannot be deleted.
        if table == "Concept":
            child_concepts = _scalar(
                _execute(
                    conn,
                    "MATCH (c:Concept)-[:PartOf]->(n:Concept {id: $pk}) RETURN count(c)",
                    {"pk": id},
                )
            )
            if child_concepts > 0:
                return {
                    "status": "error",
                    "detail": (
                        f"Concept '{id}' has {child_concepts} child Concept(s) via PartOf; "
                        "re-parent or delete them first"
                    ),
                }
            child_files = _scalar(
                _execute(
                    conn,
                    "MATCH (f:SourceFile)-[:BelongsTo]->(n:Concept {id: $pk}) RETURN count(f)",
                    {"pk": id},
                )
            )
            if child_files > 0:
                return {
                    "status": "error",
                    "detail": (
                        f"Concept '{id}' has {child_files} SourceFile(s) belonging to it; "
                        "re-link or delete them first"
                    ),
                }

        # Any remaining incident edges require opt-in detach.
        if not detach:
            edges = _scalar(
                _execute(
                    conn,
                    f"MATCH (n:{table} {{{pk_field}: $pk}})-[r]-() RETURN count(r)",
                    {"pk": id},
                )
            )
            if edges > 0:
                return {
                    "status": "error",
                    "detail": (
                        f"{table} node '{id}' has {edges} incident edge(s); "
                        "pass detach=True to drop them"
                    ),
                }

        op = "DETACH DELETE" if detach else "DELETE"
        _execute(
            conn,
            f"MATCH (n:{table} {{{pk_field}: $pk}}) {op} n",
            {"pk": id},
        )
    return {"status": "ok", "table": table, "id": id}


def delete_edge(
    db_path: Path,
    rel_type: str,
    from_id: str,
    to_id: str,
) -> dict[str, Any]:
    """Delete a relationship between two nodes.

    Returns ``{"status": "error", ...}`` if the relationship type is unknown
    or the edge does not exist.
    """
    if rel_type not in REL_ENDPOINTS:
        return {"status": "error", "detail": f"Unknown relationship type: {rel_type}"}

    from_table, to_table = REL_ENDPOINTS[rel_type]
    from_pk = PK_MAP[from_table]
    to_pk = PK_MAP[to_table]

    match_clause = (
        f"MATCH (a:{from_table} {{{from_pk}: $from_id}})"
        f"-[r:{rel_type}]->"
        f"(b:{to_table} {{{to_pk}: $to_id}})"
    )
    with _opened(db_path) as conn:
        check = _execute(
            conn,
            f"{match_clause} RETURN count(r)",
            {"from_id": from_id, "to_id": to_id},
        )
        if _scalar(check) == 0:
            return {
                "status": "error",
                "detail": f"{rel_type} edge from '{from_id}' to '{to_id}' not found",
            }

        _execute(
            conn,
            f"{match_clause} DELETE r",
            {"from_id": from_id, "to_id": to_id},
        )
    return {"status": "ok", "rel_type": rel_type, "from": from_id, "to": to_id}


def run_query(db_path: Path, cypher: str) -> list[dict[str, Any]]:
    """Run a read-only Cypher query and return a list of dicts."""
    with _opened(db_path, read_only=True) as conn:
        result = _execute(conn, cypher)
        columns = result.get_column_names()
        rows: list[dict[str, Any]] = []
        while result.has_next():
            values = result.get_next()
            rows.append(dict(zip(columns, values, strict=True)))
    return rows


def export_csv(db_path: Path, csv_dir: Path) -> None:
    """Export all tables to CSV files.

    Uses ``COPY (MATCH ...) TO`` syntax with explicit column enumeration.
    Does NOT write headers -- KuzuDB ``COPY FROM`` expects headerless CSV.
    Does NOT include the derived ``embedding`` column on any table.
    """
    csv_dir.mkdir(parents=True, exist_ok=True)
    with _opened(db_path) as conn:
        # Export node tables
        for table in NODE_TABLES:
            csv_path = csv_dir / CSV_FILES[table]
            cols = NODE_COLUMNS[table]
            return_clause = ", ".join(f"n.{c}" for c in cols)
            cypher = f"COPY (MATCH (n:{table}) RETURN {return_clause}) TO '{csv_path}'"
            _execute(conn, cypher)

        # Export relationship tables
        for rel in REL_TABLES:
            csv_path = csv_dir / CSV_FILES[rel]
            from_table, to_table = REL_ENDPOINTS[rel]
            from_pk = PK_MAP[from_table]
            to_pk = PK_MAP[to_table]
            cypher = (
                f"COPY (MATCH (a:{from_table})-[r:{rel}]->(b:{to_table}) "
                f"RETURN a.{from_pk}, b.{to_pk}, r.description, r.git_revision) "
                f"TO '{csv_path}'"
            )
            _execute(conn, cypher)


def rebuild_from_csv(db_path: Path, csv_dir: Path) -> None:
    """Rebuild KuzuDB from CSV files.

    Drops the existing database (by deleting the file), re-creates the schema,
    and imports all CSVs.  Node tables are imported first, then relationships.
    """
    # Remove existing DB
    if db_path.exists():
        db_path.unlink()
    wal = Path(str(db_path) + ".wal")
    if wal.exists():
        wal.unlink()

    init_schema(db_path)
    # Fresh schemas already carry the embedding column via DDL; this extra
    # migration call is a no-op there but keeps the helper as a single
    # reliable entry point for older DBs encountered elsewhere.
    migrate_embedding_column(db_path)

    with _opened(db_path) as conn:
        # Import node tables.  CSV does not contain the derived ``embedding``
        # column, so list the populated columns explicitly; KuzuDB would
        # otherwise expect one value per DDL column.
        for table in NODE_TABLES:
            csv_path = csv_dir / CSV_FILES[table]
            if csv_path.exists() and csv_path.stat().st_size > 0:
                col_list = ", ".join(NODE_COLUMNS[table])
                _execute(conn, f"COPY {table}({col_list}) FROM '{csv_path}'")

        # Import relationship tables.  For REL COPY, endpoint keys are implicit
        # in the first two CSV columns; we only list the non-endpoint props we
        # actually exported (description, git_revision -- never embedding).
        for rel in REL_TABLES:
            csv_path = csv_dir / CSV_FILES[rel]
            if csv_path.exists() and csv_path.stat().st_size > 0:
                _execute(conn, f"COPY {rel}(description, git_revision) FROM '{csv_path}'")


def get_stats(db_path: Path) -> dict[str, Any]:
    """Return node/edge counts per table."""
    node_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    with _opened(db_path, read_only=True) as conn:
        for table in NODE_TABLES:
            result = _execute(conn, f"MATCH (n:{table}) RETURN count(n)")
            node_counts[table] = _scalar(result) if result.has_next() else 0

        for rel in REL_TABLES:
            from_table, to_table = REL_ENDPOINTS[rel]
            result = _execute(
                conn, f"MATCH (:{from_table})-[r:{rel}]->(:{to_table}) RETURN count(r)"
            )
            edge_counts[rel] = _scalar(result) if result.has_next() else 0

    return {"node_counts": node_counts, "edge_counts": edge_counts}

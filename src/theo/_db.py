"""KuzuDB operations for the Theo knowledge graph.

All functions accept a ``db_path`` and open a fresh connection per call.
This keeps the API stateless and COW-friendly (the caller may pass either
the real path or a temporary copy).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import real_ladybug as lb

from theo._schema import (
    CSV_FILES,
    FIELD_MAP,
    NODE_COLUMNS,
    NODE_DDL,
    NODE_TABLES,
    PK_MAP,
    REL_DDL,
    REL_ENDPOINTS,
    REL_TABLES,
)


def _connect(db_path: Path) -> tuple[lb.Database, lb.Connection]:
    db = lb.Database(str(db_path))
    conn = lb.Connection(db)
    return db, conn


def _connect_ro(db_path: Path) -> tuple[lb.Database, lb.Connection]:
    """Open a read-only connection to prevent accidental mutation."""
    db = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(db)
    return db, conn


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


def init_schema(db_path: Path) -> None:
    """Create all node and relationship tables in a new KuzuDB database."""
    _db, conn = _connect(db_path)
    for ddl in NODE_DDL.values():
        _execute(conn, ddl)
    for ddl in REL_DDL.values():
        _execute(conn, ddl)


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

    _db, conn = _connect(db_path)

    if set_fields:
        set_clause = ", ".join(f"n.{k} = ${k}" for k in set_fields)
        cypher = f"MERGE (n:{table} {{{pk_field}: ${pk_field}}}) SET {set_clause}"
    else:
        cypher = f"MERGE (n:{table} {{{pk_field}: ${pk_field}}})"

    params: dict[str, Any] = {pk_field: pk_value, **set_fields}
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

    _db, conn = _connect(db_path)

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


def run_query(db_path: Path, cypher: str) -> list[dict[str, Any]]:
    """Run a read-only Cypher query and return a list of dicts."""
    _db, conn = _connect_ro(db_path)
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
    """
    csv_dir.mkdir(parents=True, exist_ok=True)
    _db, conn = _connect(db_path)

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
            f"RETURN a.{from_pk}, b.{to_pk}, r.description, r.git_revision) TO '{csv_path}'"
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
    _db, conn = _connect(db_path)

    # Import node tables
    for table in NODE_TABLES:
        csv_path = csv_dir / CSV_FILES[table]
        if csv_path.exists() and csv_path.stat().st_size > 0:
            _execute(conn, f"COPY {table} FROM '{csv_path}'")

    # Import relationship tables
    for rel in REL_TABLES:
        csv_path = csv_dir / CSV_FILES[rel]
        if csv_path.exists() and csv_path.stat().st_size > 0:
            _execute(conn, f"COPY {rel} FROM '{csv_path}'")


def get_stats(db_path: Path) -> dict[str, Any]:
    """Return node/edge counts per table."""
    _db, conn = _connect_ro(db_path)
    node_counts: dict[str, int] = {}
    for table in NODE_TABLES:
        result = _execute(conn, f"MATCH (n:{table}) RETURN count(n)")
        node_counts[table] = _scalar(result) if result.has_next() else 0

    edge_counts: dict[str, int] = {}
    for rel in REL_TABLES:
        from_table, to_table = REL_ENDPOINTS[rel]
        result = _execute(conn, f"MATCH (:{from_table})-[r:{rel}]->(:{to_table}) RETURN count(r)")
        edge_counts[rel] = _scalar(result) if result.has_next() else 0

    return {"node_counts": node_counts, "edge_counts": edge_counts}

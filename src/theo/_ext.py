"""Shared KuzuDB extension helpers and type-narrowing utilities."""

from __future__ import annotations

import contextlib
from typing import Any

import real_ladybug as lb


def run_cypher(
    db_path: str,
    cypher: str,
    *,
    read_only: bool = True,
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Open a database, execute a single Cypher statement, and return rows.

    This is the canonical open-execute-close lifecycle shared by all code that
    needs to run a query against a database path.  Callers should add their own
    access-control checks (e.g. mutation-keyword guards) *before* calling this
    helper.

    Args:
        db_path: Absolute path to the KuzuDB database directory.
        cypher: The Cypher query string.
        read_only: If ``True`` (default), open the database in read-only mode.
        parameters: Optional parameter dict for parameterised queries.

    Returns:
        A list of result rows, each represented as a dict mapping column names
        to values.
    """
    db = lb.Database(db_path, read_only=read_only)
    conn = lb.Connection(db)
    try:
        rows = collect_rows(execute(conn, cypher, parameters))
    finally:
        del conn
        db.close()
    return rows


def load_vector_ext(conn: lb.Connection) -> None:
    """Install (once) and load the VECTOR extension for a connection."""
    with contextlib.suppress(RuntimeError):
        conn.execute("INSTALL VECTOR")
    conn.execute("LOAD EXTENSION VECTOR")


def execute(
    conn: lb.Connection,
    query: str,
    parameters: dict[str, Any] | None = None,
) -> lb.QueryResult:
    """Execute a single Cypher statement and return the QueryResult.

    ``Connection.execute`` is typed as returning ``QueryResult | list[QueryResult]``
    (the list form only appears for multi-statement strings).  This wrapper
    narrows the type for the common single-statement case so that callers
    don't need repeated ``assert isinstance`` or ``# type: ignore`` lines.
    """
    result = conn.execute(query, parameters)
    if isinstance(result, list):
        # Multi-statement execution -- take the last result.
        return result[-1]
    return result


def get_next_list(result: lb.QueryResult) -> list[Any]:
    """Get the next row as a list (narrowing the union type).

    ``QueryResult.get_next()`` is typed as ``list[Any] | dict[str, Any]``.
    In practice it always returns a list for positional queries (``RETURN a, b``).
    This helper narrows the type so callers can index with ``row[0]`` without
    mypy errors.
    """
    row = result.get_next()
    if isinstance(row, dict):
        return list(row.values())
    return row


def collect_rows(result: lb.QueryResult) -> list[dict[str, Any]]:
    """Drain a KuzuDB query result into a list of dicts.

    Common pattern used by query, semantic_search, and backfill_embeddings.
    Each row is a dict mapping column names to values.
    """
    cols: list[str] = result.get_column_names()
    rows: list[dict[str, Any]] = []
    while result.has_next():
        rows.append(dict(zip(cols, get_next_list(result), strict=True)))
    return rows

"""Shared KuzuDB extension helpers and type-narrowing utilities."""

from __future__ import annotations

import contextlib
from typing import Any

import real_ladybug as lb


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

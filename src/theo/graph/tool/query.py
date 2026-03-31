"""
Run a read-only Cypher query against the code-intelligence graph.

    query(db_path, cypher) -> list[dict]

Returns: list of result rows as dicts.
"""

from __future__ import annotations

import re
from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo.graph._ext import execute

_log = get_logger("query")

# Conservative guard: rejects queries containing mutation keywords.
# Note: this can produce false positives for string literals containing these
# keywords (e.g. WHERE n.x CONTAINS 'SET').  This is an intentional trade-off
# favouring safety -- the query tool should only be used for genuine reads.
_MUTATING_RE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP)\b", re.IGNORECASE)


def query(db_path: str, cypher: str) -> list[dict[str, Any]]:
    if _MUTATING_RE.search(cypher):
        raise ValueError(f"Only read-only queries are allowed, got: {cypher[:80]}")
    _log.info("[READ] Graph query: %s", cypher[:120])
    db = lb.Database(db_path, read_only=True)
    conn = lb.Connection(db)
    result = execute(conn, cypher)
    columns: list[str] = result.get_column_names()
    rows: list[dict[str, Any]] = []
    while result.has_next():
        row = result.get_next()
        rows.append(dict(zip(columns, row, strict=True)))
    return rows


if __name__ == "__main__":
    import json
    import sys

    db_path = sys.argv[1]
    cypher_query = sys.argv[2]
    print(json.dumps(query(db_path, cypher_query), indent=2, default=str))

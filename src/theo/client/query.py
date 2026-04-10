"""
Run a read-only Cypher query against the code-intelligence graph.

    query(db_path, cypher) -> list[dict]

Returns: list of result rows as dicts.
"""

from __future__ import annotations

import re
from typing import Any

from theo import get_logger
from theo._ext import run_cypher

_log = get_logger("query")

# Conservative guard: rejects queries containing mutation keywords.
# Note: this can produce false positives for string literals containing these
# keywords (e.g. WHERE n.x CONTAINS 'SET').  This is an intentional trade-off
# favouring safety -- the query tool should only be used for genuine reads.
_MUTATING_RE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP)\b", re.IGNORECASE)


def query(db_path: str, cypher: str) -> list[dict[str, Any]]:
    if _MUTATING_RE.search(cypher):
        raise ValueError(f"Only read-only queries are allowed, got: {cypher[:80]}")
    _log.info("[READ] Graph query on %s: %s", db_path, cypher[:120])
    return run_cypher(db_path, cypher, read_only=True)


if __name__ == "__main__":
    import json
    import sys

    db_path = sys.argv[1]
    cypher_query = sys.argv[2]
    print(json.dumps(query(db_path, cypher_query), indent=2, default=str))

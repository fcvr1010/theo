"""
Run a Cypher query against a graph database at a given path.

    query(db_path, cypher, read_only=True) -> list[dict]

Unlike ``theo.client.query`` which resolves the DB via repo name and enforces
read-only mode, this tool accepts a direct ``db_path``.  This makes it usable
for COW copies during write sessions where the client's config-based resolution
does not apply.

By default the database is opened in read-only mode.  Pass ``read_only=False``
to allow mutation queries (use with caution -- prefer the dedicated upsert tools
for writes).

Returns: list of result rows as dicts.
"""

from __future__ import annotations

from typing import Any

from theo import get_logger
from theo._ext import run_cypher

_log = get_logger("tools.query")


def query(
    db_path: str,
    cypher: str,
    read_only: bool = True,
) -> list[dict[str, Any]]:
    """Execute a Cypher query against the database at *db_path*.

    Args:
        db_path: Absolute path to the KuzuDB database directory.
        cypher: The Cypher query string.
        read_only: If ``True`` (default), open the database in read-only mode.

    Returns:
        A list of result rows, each represented as a dict mapping column names
        to values.
    """
    _log.info("[QUERY] %s (ro=%s): %s", db_path, read_only, cypher[:120])
    return run_cypher(db_path, cypher, read_only=read_only)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: python -m theo.tools.query <db_path> '<cypher>' [--rw]",
            file=sys.stderr,
        )
        sys.exit(1)

    db_path = sys.argv[1]
    cypher_query = sys.argv[2]
    rw = "--rw" in sys.argv[3:]
    print(json.dumps(query(db_path, cypher_query, read_only=not rw), indent=2, default=str))

"""
Return concept and source-file counts from a Theo graph database.

    get_node_counts(db_path) -> dict

Returns: {concepts: int, source_files: int}
"""

from __future__ import annotations

import real_ladybug as lb

from theo._ext import collect_rows, execute


def get_node_counts(db_path: str) -> dict[str, int]:
    """Return concept and source-file counts from a LadybugDB database.

    Args:
        db_path: Path to the LadybugDB database directory.

    Returns:
        Dict with keys ``concepts`` and ``source_files``, each an int count.
    """
    db = lb.Database(db_path, read_only=True)
    conn = lb.Connection(db)
    try:
        concept_rows = collect_rows(execute(conn, "MATCH (c:Concept) RETURN count(c) AS cnt"))
        file_rows = collect_rows(execute(conn, "MATCH (f:SourceFile) RETURN count(f) AS cnt"))
    finally:
        del conn
        db.close()

    concepts = int(concept_rows[0]["cnt"]) if concept_rows else 0
    files = int(file_rows[0]["cnt"]) if file_rows else 0
    return {"concepts": concepts, "source_files": files}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: node_counts.py <db_path>", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(get_node_counts(sys.argv[1]), indent=2))

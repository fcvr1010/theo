"""
Initialise a Theo graph database with the code-intelligence schema (idempotent).

    init_db(db_path) -> dict

Returns: {status: "ok", tables: [...]}

Note: this is a simple "run all CREATE IF NOT EXISTS" init.  If the schema
evolves significantly, a proper migration framework can be introduced later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import real_ladybug as lb

from theo.graph._schema import ALLOWED_REL_TYPES, EMBEDDING_DIM, TABLES


def init_db(db_path: str) -> dict[str, Any]:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = lb.Database(db_path)
    conn = lb.Connection(db)

    dim = EMBEDDING_DIM

    stmts = [
        # Node tables
        f"""CREATE NODE TABLE IF NOT EXISTS Concept(
            id STRING PRIMARY KEY,
            name STRING,
            level INT32,
            kind STRING,
            description STRING,
            notes STRING,
            git_revision STRING,
            embedding FLOAT[{dim}]
        )""",
        f"""CREATE NODE TABLE IF NOT EXISTS SourceFile(
            path STRING PRIMARY KEY,
            name STRING,
            language STRING,
            description STRING,
            notes STRING,
            line_count INT32,
            git_revision STRING,
            embedding FLOAT[{dim}]
        )""",
        # Relationship tables
        "CREATE REL TABLE IF NOT EXISTS PartOf(FROM Concept TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS BelongsTo(FROM SourceFile TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS InteractsWith("
        "FROM Concept TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS DependsOn(FROM Concept TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS Imports("
        "FROM SourceFile TO SourceFile, description STRING)",
    ]

    for stmt in stmts:
        conn.execute(stmt)

    del conn
    db.close()

    # Return table names from the canonical schema constants rather than
    # parsing them out of DDL strings.
    tables = list(TABLES) + sorted(ALLOWED_REL_TYPES)

    return {"status": "ok", "tables": tables}


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(init_db(sys.argv[1]), indent=2))

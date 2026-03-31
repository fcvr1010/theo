"""
Initialise a Theo graph database with the code-intelligence schema (idempotent).

    init_db(db_path) -> dict

Returns: {status: "ok", tables: [...]}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import real_ladybug as lb


def init_db(db_path: str) -> dict[str, Any]:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = lb.Database(db_path)
    conn = lb.Connection(db)

    stmts = [
        # Node tables
        """CREATE NODE TABLE IF NOT EXISTS Concept(
            id STRING PRIMARY KEY,
            name STRING,
            level INT32,
            kind STRING,
            description STRING,
            notes STRING,
            git_revision STRING
        )""",
        """CREATE NODE TABLE IF NOT EXISTS SourceFile(
            path STRING PRIMARY KEY,
            name STRING,
            language STRING,
            description STRING,
            notes STRING,
            line_count INT32,
            git_revision STRING
        )""",
        """CREATE NODE TABLE IF NOT EXISTS Symbol(
            id STRING PRIMARY KEY,
            name STRING,
            kind STRING,
            file_path STRING,
            description STRING,
            notes STRING,
            git_revision STRING
        )""",
        # Relationship tables
        "CREATE REL TABLE IF NOT EXISTS PartOf(FROM Concept TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS BelongsTo(FROM SourceFile TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS DefinedIn(FROM Symbol TO SourceFile)",
        "CREATE REL TABLE IF NOT EXISTS InteractsWith("
        "FROM Concept TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS DependsOn(FROM Concept TO Concept, description STRING)",
        "CREATE REL TABLE IF NOT EXISTS Imports("
        "FROM SourceFile TO SourceFile, description STRING)",
    ]

    tables: list[str] = []
    for stmt in stmts:
        conn.execute(stmt)
        # Extract table name for reporting.
        for keyword in ("TABLE", "table"):
            if keyword in stmt:
                parts = stmt.split(keyword, 1)[1].strip().split("(", 1)
                name = parts[0].strip().split()[-1]
                tables.append(name)
                break

    # Migrate: add embedding column to node tables (idempotent).
    for table in ("Concept", "SourceFile", "Symbol"):
        try:
            conn.execute(f"ALTER TABLE {table} ADD embedding FLOAT[768]")
        except RuntimeError as e:
            if "already has property" in str(e):
                pass  # Column exists -- migration already applied.
            else:
                raise

    # Migrate: add git_revision column to node tables (idempotent).
    for table in ("Concept", "SourceFile", "Symbol"):
        try:
            conn.execute(f"ALTER TABLE {table} ADD git_revision STRING")
        except RuntimeError as e:
            if "already has property" in str(e):
                pass  # Column exists -- migration already applied.
            else:
                raise

    return {"status": "ok", "tables": tables}


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(init_db(sys.argv[1]), indent=2))

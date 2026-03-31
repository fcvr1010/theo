"""
MERGE (upsert) a node in the code-intelligence graph.

    upsert_node(db_path, table, properties) -> dict

table: "Concept" | "SourceFile"
properties: dict with the primary key and any fields to set.

Returns: {status: "ok", table, key}
"""

from __future__ import annotations

from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo.graph._schema import ALLOWED_TABLES, FIELD_RE, PK_MAP

_log = get_logger("upsert_node")


def upsert_node(db_path: str, table: str, properties: dict[str, Any]) -> dict[str, Any]:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table: {table!r}")
    for k in properties:
        if not FIELD_RE.match(k):
            raise ValueError(f"Invalid field name: {k!r}")

    db = lb.Database(db_path)
    conn = lb.Connection(db)

    pk_field = PK_MAP[table]
    pk_value = properties[pk_field]
    _log.info("[WRITE] Upsert node: %s key=%s", table, pk_value)

    set_clauses: list[str] = []
    params: dict[str, Any] = {"pk": pk_value}
    for i, (k, v) in enumerate(properties.items()):
        if k == pk_field:
            continue
        param_name = f"p{i}"
        set_clauses.append(f"n.{k} = ${param_name}")
        params[param_name] = v

    on_create = f"ON CREATE SET {', '.join(set_clauses)}" if set_clauses else ""
    on_match = f"ON MATCH SET {', '.join(set_clauses)}" if set_clauses else ""

    cypher = f"MERGE (n:{table} {{{pk_field}: $pk}}) {on_create} {on_match}"
    conn.execute(cypher, params)

    del conn
    db.close()

    return {"status": "ok", "table": table, "key": pk_value}


if __name__ == "__main__":
    import json
    import sys

    db_path = sys.argv[1]
    table = sys.argv[2]
    props = json.loads(sys.argv[3])
    print(json.dumps(upsert_node(db_path, table, props), indent=2))

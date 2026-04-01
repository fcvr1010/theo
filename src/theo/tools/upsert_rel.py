"""
Create a relationship if it does not already exist in the code-intelligence graph.

    upsert_rel(db_path, rel_type, from_table, from_id, to_table, to_id, properties=None) -> dict

Returns: {status: "ok", rel_type, from: from_id, to: to_id}
"""

from __future__ import annotations

from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo._schema import ALLOWED_REL_TYPES, ALLOWED_TABLES, FIELD_RE, PK_MAP

_log = get_logger("upsert_rel")


def upsert_rel(
    db_path: str,
    rel_type: str,
    from_table: str,
    from_id: str,
    to_table: str,
    to_id: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if rel_type not in ALLOWED_REL_TYPES:
        raise ValueError(f"Invalid rel_type: {rel_type!r}")
    if from_table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid from_table: {from_table!r}")
    if to_table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid to_table: {to_table!r}")
    if properties:
        for k in properties:
            if not FIELD_RE.match(k):
                raise ValueError(f"Invalid field name: {k!r}")

    _log.info("[WRITE] Upsert rel: %s -[%s]-> %s", from_id, rel_type, to_id)

    db = lb.Database(db_path)
    conn = lb.Connection(db)

    from_pk = PK_MAP[from_table]
    to_pk = PK_MAP[to_table]

    params: dict[str, Any] = {"from_id": from_id, "to_id": to_id}

    set_clause = ""
    if properties:
        parts: list[str] = []
        for i, (k, v) in enumerate(properties.items()):
            param_name = f"p{i}"
            parts.append(f"r.{k} = ${param_name}")
            params[param_name] = v
        set_clause = "ON CREATE SET " + ", ".join(parts) + " ON MATCH SET " + ", ".join(parts)

    cypher = (
        f"MATCH (a:{from_table} {{{from_pk}: $from_id}}), "
        f"(b:{to_table} {{{to_pk}: $to_id}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) {set_clause}"
    )
    conn.execute(cypher, params)

    del conn
    db.close()

    return {"status": "ok", "rel_type": rel_type, "from": from_id, "to": to_id}


if __name__ == "__main__":
    import json
    import sys

    db_path = sys.argv[1]
    rel_type = sys.argv[2]
    from_table = sys.argv[3]
    from_id = sys.argv[4]
    to_table = sys.argv[5]
    to_id = sys.argv[6]
    props = json.loads(sys.argv[7]) if len(sys.argv) > 7 else None
    print(
        json.dumps(
            upsert_rel(db_path, rel_type, from_table, from_id, to_table, to_id, props),
            indent=2,
        )
    )

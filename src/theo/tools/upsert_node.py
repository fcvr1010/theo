"""
MERGE (upsert) a node in the code-intelligence graph.

    upsert_node(db_path, table, properties) -> dict

table: "Concept" | "SourceFile"
properties: dict with the primary key and any schema-defined fields to set.
Only fields listed in ``ALLOWED_FIELDS[table]`` are accepted.

Automatically computes a semantic embedding from the node's ``description``
and ``notes`` fields whenever either is present in *properties*.  The caller
must NOT pass an ``embedding`` vector -- it is internally managed and derived
transparently from the text fields.

Returns: {status: "ok", table, key, embedding_computed: bool}
"""

from __future__ import annotations

from typing import Any

import real_ladybug as lb

from theo import get_logger
from theo._schema import ALLOWED_FIELDS, ALLOWED_TABLES, PK_MAP

_log = get_logger("upsert_node")

# Text fields that feed into the semantic embedding.
_EMBEDDING_TEXT_FIELDS: tuple[str, ...] = ("description", "notes")


def _compute_embedding(properties: dict[str, Any]) -> list[float] | None:
    """Compute an embedding from description/notes if either is present.

    Returns the embedding vector, or ``None`` if no text fields are available
    to embed.  Imports ``embed_text`` lazily to avoid loading the model on
    every upsert that does not need it.
    """
    parts = [properties.get(f) or "" for f in _EMBEDDING_TEXT_FIELDS]
    text = "\n\n".join(parts).strip()
    if not text:
        return None

    from theo._embed import embed_text

    _log.info("[EMBED] Auto-computing embedding for upsert (%d chars)", len(text))
    return embed_text([text])[0]


def upsert_node(db_path: str, table: str, properties: dict[str, Any]) -> dict[str, Any]:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table: {table!r}")
    allowed = ALLOWED_FIELDS[table]
    bad = {k for k in properties if k not in allowed}
    if bad:
        raise ValueError(
            f"Unknown field(s) for {table}: {sorted(bad)}. "
            f"Allowed fields: {sorted(allowed)}"
        )

    # Auto-compute embedding when description or notes are present in properties
    # (even if empty -- an empty string should clear the old embedding).
    embedding_computed = False
    has_text_fields = any(f in properties for f in _EMBEDDING_TEXT_FIELDS)
    if has_text_fields:
        embedding = _compute_embedding(properties)
        properties = {**properties, "embedding": embedding}
        embedding_computed = True

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

    return {
        "status": "ok",
        "table": table,
        "key": pk_value,
        "embedding_computed": embedding_computed,
    }


if __name__ == "__main__":
    import json
    import sys

    db_path = sys.argv[1]
    table = sys.argv[2]
    props = json.loads(sys.argv[3])
    print(json.dumps(upsert_node(db_path, table, props), indent=2))

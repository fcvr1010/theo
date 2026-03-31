"""Shared schema constants for the code-intelligence graph."""

from __future__ import annotations

import re

TABLES: tuple[str, ...] = ("Concept", "SourceFile")

PK_MAP: dict[str, str] = {"Concept": "id", "SourceFile": "path"}

ALLOWED_TABLES: frozenset[str] = frozenset(TABLES)

ALLOWED_REL_TYPES: frozenset[str] = frozenset(
    {
        "PartOf",
        "BelongsTo",
        "InteractsWith",
        "DependsOn",
        "Imports",
    }
)

# Regex for validating user-supplied field names in upsert operations.
FIELD_RE: re.Pattern[str] = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)

# HNSW vector index specifications: (table_name, index_name).
# Convention: {table_lower}_emb_idx.  Used by manage_indexes (create/drop)
# and semantic_search (query).
INDEX_SPECS: list[tuple[str, str]] = [
    ("Concept", "concept_emb_idx"),
    ("SourceFile", "sourcefile_emb_idx"),
]

# Convenience dict for index lookups by table name.
INDEX_MAP: dict[str, str] = dict(INDEX_SPECS)

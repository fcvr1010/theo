"""Structural schema definitions for the code-intelligence graph.

This module defines the graph type system: node tables, primary keys,
allowed relationship types, field validation, and vector index specs.
These are structural constants that are not user-configurable.

Configurable settings (embedding model name, embedding dimension, paths)
live in ``theo.config.TheoConfig``.
"""

from __future__ import annotations

import re

from theo.config import TheoConfig

# Embedding vector dimension -- sourced from TheoConfig so it can be
# overridden via the THEO_EMBEDDING_DIM environment variable.
EMBEDDING_DIM: int = TheoConfig().embedding_dim

TABLES: tuple[str, ...] = ("Concept", "SourceFile")

PK_MAP: dict[str, str] = {"Concept": "id", "SourceFile": "path"}

ALLOWED_TABLES: frozenset[str] = frozenset(TABLES)

# Caller-facing fields per node table.  Derived from the DDL in init_db.py,
# but **excluding** ``embedding`` which is internally managed by upsert_node.
ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "Concept": frozenset({"id", "name", "level", "kind", "description", "notes", "git_revision"}),
    "SourceFile": frozenset(
        {"path", "name", "language", "description", "notes", "line_count", "git_revision"}
    ),
}

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

"""Graph schema constants for the Theo knowledge graph.

Defines table names, primary keys, field allowlists, relationship endpoints,
foreign-key field names for CSV export/import, and CSV file names.
"""

from __future__ import annotations

NODE_TABLES: list[str] = ["Concept", "SourceFile"]
REL_TABLES: list[str] = ["PartOf", "BelongsTo", "InteractsWith", "DependsOn", "Imports"]

# Embedding configuration.  Every table in EMBEDDABLE_TABLES carries an
# ``embedding FLOAT[EMBEDDING_DIM]`` column (populated outside CSV).
#
# HNSW vector indexes are a node-table feature in KuzuDB; relationship
# embeddings are searched via brute-force cosine similarity only.  Hence
# ``HNSW_INDEX_NAMES`` only covers node tables.
EMBEDDING_DIM: int = 768
EMBEDDABLE_TABLES: list[str] = NODE_TABLES + REL_TABLES
HNSW_INDEX_NAMES: dict[str, str] = {t: f"{t.lower()}_emb_idx" for t in NODE_TABLES}

# Primary keys for each node table
PK_MAP: dict[str, str] = {
    "Concept": "id",
    "SourceFile": "path",
}

# Valid fields for each table (used for validation in upsert)
CONCEPT_FIELDS: set[str] = {
    "id",
    "name",
    "level",
    "description",
    "notes",
    "git_revision",
}
SOURCE_FILE_FIELDS: set[str] = {
    "path",
    "name",
    "description",
    "notes",
    "git_revision",
}

FIELD_MAP: dict[str, set[str]] = {
    "Concept": CONCEPT_FIELDS,
    "SourceFile": SOURCE_FILE_FIELDS,
}

# Relationship endpoints (from_table, to_table)
REL_ENDPOINTS: dict[str, tuple[str, str]] = {
    "PartOf": ("Concept", "Concept"),
    "BelongsTo": ("SourceFile", "Concept"),
    "InteractsWith": ("Concept", "Concept"),
    "DependsOn": ("Concept", "Concept"),
    "Imports": ("SourceFile", "SourceFile"),
}

# FK field names in CSV (from_pk, to_pk)
# Used in future CSV validation and import tooling
REL_FK_FIELDS: dict[str, tuple[str, str]] = {
    "PartOf": ("from_id", "to_id"),
    "BelongsTo": ("from_path", "to_id"),
    "InteractsWith": ("from_id", "to_id"),
    "DependsOn": ("from_id", "to_id"),
    "Imports": ("from_path", "to_path"),
}

# CSV file names
CSV_FILES: dict[str, str] = {
    "Concept": "concepts.csv",
    "SourceFile": "source_files.csv",
    "PartOf": "part_of.csv",
    "BelongsTo": "belongs_to.csv",
    "InteractsWith": "interacts_with.csv",
    "DependsOn": "depends_on.csv",
    "Imports": "imports.csv",
}

# Ordered field lists for CSV export (determines column order)
CONCEPT_COLUMNS: list[str] = [
    "id",
    "name",
    "level",
    "description",
    "notes",
    "git_revision",
]
SOURCE_FILE_COLUMNS: list[str] = [
    "path",
    "name",
    "description",
    "notes",
    "git_revision",
]

NODE_COLUMNS: dict[str, list[str]] = {
    "Concept": CONCEPT_COLUMNS,
    "SourceFile": SOURCE_FILE_COLUMNS,
}

# DDL for creating node tables.  The ``embedding FLOAT[768]`` column is
# populated only in-memory (never exported to CSV): it is derived from
# ``description`` / ``notes`` and rebuilt by ``theo reload`` / ``theo reindex``.
NODE_DDL: dict[str, str] = {
    "Concept": (
        "CREATE NODE TABLE Concept("
        "id STRING PRIMARY KEY, "
        "name STRING, "
        "level INT32, "
        "description STRING, "
        "notes STRING, "
        "git_revision STRING, "
        f"embedding FLOAT[{EMBEDDING_DIM}])"
    ),
    "SourceFile": (
        "CREATE NODE TABLE SourceFile("
        "path STRING PRIMARY KEY, "
        "name STRING, "
        "description STRING, "
        "notes STRING, "
        "git_revision STRING, "
        f"embedding FLOAT[{EMBEDDING_DIM}])"
    ),
}

# DDL for creating relationship tables.  Relationship embeddings encode just
# ``description`` (rel tables have no ``notes`` today).
REL_DDL: dict[str, str] = {
    "PartOf": (
        "CREATE REL TABLE PartOf(FROM Concept TO Concept, "
        f"description STRING, git_revision STRING, embedding FLOAT[{EMBEDDING_DIM}])"
    ),
    "BelongsTo": (
        "CREATE REL TABLE BelongsTo(FROM SourceFile TO Concept, "
        f"description STRING, git_revision STRING, embedding FLOAT[{EMBEDDING_DIM}])"
    ),
    "InteractsWith": (
        "CREATE REL TABLE InteractsWith(FROM Concept TO Concept, "
        f"description STRING, git_revision STRING, embedding FLOAT[{EMBEDDING_DIM}])"
    ),
    "DependsOn": (
        "CREATE REL TABLE DependsOn(FROM Concept TO Concept, "
        f"description STRING, git_revision STRING, embedding FLOAT[{EMBEDDING_DIM}])"
    ),
    "Imports": (
        "CREATE REL TABLE Imports(FROM SourceFile TO SourceFile, "
        f"description STRING, git_revision STRING, embedding FLOAT[{EMBEDDING_DIM}])"
    ),
}

"""Shared schema constants for the code-intelligence graph."""

from __future__ import annotations

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

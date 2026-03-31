"""Shared schema constants for the code-intelligence graph."""

from __future__ import annotations

TABLES: tuple[str, ...] = ("Concept", "SourceFile", "Symbol")

PK_MAP: dict[str, str] = {"Concept": "id", "SourceFile": "path", "Symbol": "id"}

ALLOWED_TABLES: frozenset[str] = frozenset(TABLES)

ALLOWED_REL_TYPES: frozenset[str] = frozenset(
    {
        "PartOf",
        "BelongsTo",
        "DefinedIn",
        "InteractsWith",
        "DependsOn",
        "Imports",
    }
)

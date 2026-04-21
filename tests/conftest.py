"""Shared test fixtures for the Theo test suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from theo._db import init_schema
from theo._schema import CSV_FILES


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Create a fresh KuzuDB with Theo schema in a temp directory."""
    db_path = tmp_path / "theo.db"
    init_schema(db_path)
    return db_path


@pytest.fixture()
def tmp_theo_project(tmp_path: Path) -> Path:
    """Create a minimal .theo/ project structure with DB and config."""
    theo_dir = tmp_path / ".theo"
    theo_dir.mkdir()

    # Create empty CSV files
    for csv_name in CSV_FILES.values():
        (theo_dir / csv_name).touch()

    # Create DB
    db_dir = theo_dir / "db"
    db_dir.mkdir()
    db_path = db_dir / "theo.db"
    init_schema(db_path)

    # Create config
    config = {
        "project_slug": tmp_path.name,
        "db_path": ".theo/db/theo.db",
        "last_indexed_commit": None,
        "created": "2026-01-01T00:00:00+00:00",
    }
    (theo_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    return tmp_path

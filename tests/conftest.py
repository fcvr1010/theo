"""Shared test fixtures for the Theo test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from theo.tools.init_db import init_db


@pytest.fixture()
def fresh_db(tmp_path: Path) -> str:
    """Create a fresh, schema-initialised database and return its path."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


@pytest.fixture()
def populated_db(fresh_db: str) -> str:
    """Create a database pre-populated with sample nodes and relationships."""
    import real_ladybug as lb

    db = lb.Database(fresh_db)
    conn = lb.Connection(db)

    # Insert sample Concepts.
    conn.execute(
        "CREATE (c:Concept {id: 'dispatch', name: 'Dispatch', level: 1, "
        "kind: 'module', description: 'Message dispatching', notes: 'Core module', "
        "git_revision: 'abc123'})"
    )
    conn.execute(
        "CREATE (c:Concept {id: 'delivery', name: 'Delivery', level: 1, "
        "kind: 'module', description: 'Message delivery pipeline', notes: 'Handles output', "
        "git_revision: 'abc123'})"
    )
    conn.execute(
        "CREATE (c:Concept {id: 'config', name: 'Config', level: 2, "
        "kind: 'module', description: 'Configuration management', notes: 'Settings', "
        "git_revision: 'abc123'})"
    )

    # Insert sample SourceFiles.
    conn.execute(
        "CREATE (f:SourceFile {path: 'src/dispatch.py', name: 'dispatch.py', "
        "language: 'python', description: 'Dispatcher implementation', "
        "notes: 'Main dispatch logic', line_count: 200, git_revision: 'abc123'})"
    )
    conn.execute(
        "CREATE (f:SourceFile {path: 'src/delivery.py', name: 'delivery.py', "
        "language: 'python', description: 'Delivery pipeline', "
        "notes: 'Output handling', line_count: 150, git_revision: 'abc123'})"
    )

    # Insert relationships.
    conn.execute(
        "MATCH (a:Concept {id: 'dispatch'}), (b:Concept {id: 'delivery'}) "
        "CREATE (a)-[:DependsOn {description: 'dispatch sends to delivery'}]->(b)"
    )
    conn.execute(
        "MATCH (f:SourceFile {path: 'src/dispatch.py'}), (c:Concept {id: 'dispatch'}) "
        "CREATE (f)-[:BelongsTo {description: 'main file'}]->(c)"
    )
    conn.execute(
        "MATCH (a:SourceFile {path: 'src/dispatch.py'}), (b:SourceFile {path: 'src/delivery.py'}) "
        "CREATE (a)-[:Imports {description: 'imports delivery'}]->(b)"
    )

    del conn
    db.close()
    return fresh_db

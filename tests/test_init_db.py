"""Tests for theo.graph.init_db."""

from __future__ import annotations

from pathlib import Path

import real_ladybug as lb

from theo.graph.init_db import init_db


class TestInitDb:
    """Test database initialisation and schema creation."""

    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "new.db")
        result = init_db(db_path)
        assert result["status"] == "ok"
        assert Path(db_path).exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "nested" / "dir" / "test.db")
        result = init_db(db_path)
        assert result["status"] == "ok"
        assert Path(db_path).parent.exists()

    def test_returns_all_table_names(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        result = init_db(db_path)
        expected_tables = {
            "Concept",
            "SourceFile",
            "PartOf",
            "BelongsTo",
            "InteractsWith",
            "DependsOn",
            "Imports",
        }
        assert set(result["tables"]) == expected_tables

    def test_idempotent_multiple_calls(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        result1 = init_db(db_path)
        result2 = init_db(db_path)
        assert result1["status"] == "ok"
        assert result2["status"] == "ok"
        assert set(result1["tables"]) == set(result2["tables"])

    def test_concept_table_has_expected_columns(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        # Insert a node using all expected columns to verify they exist.
        db_rw = lb.Database(db_path)
        conn_rw = lb.Connection(db_rw)
        conn_rw.execute(
            "CREATE (c:Concept {id: 'test', name: 'Test', level: 1, "
            "kind: 'module', description: 'desc', notes: 'notes', "
            "git_revision: 'rev1'})"
        )
        del conn_rw
        db_rw.close()
        # Open read-only after write to see the data.
        db = lb.Database(db_path, read_only=True)
        conn = lb.Connection(db)
        result = conn.execute("MATCH (c:Concept {id: 'test'}) RETURN c.git_revision")
        assert result.has_next()
        assert result.get_next()[0] == "rev1"

    def test_sourcefile_table_has_git_revision(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        db = lb.Database(db_path)
        conn = lb.Connection(db)
        conn.execute(
            "CREATE (f:SourceFile {path: 'test.py', name: 'test.py', "
            "language: 'python', description: 'desc', notes: 'notes', "
            "line_count: 10, git_revision: 'abc'})"
        )
        result = conn.execute("MATCH (f:SourceFile {path: 'test.py'}) RETURN f.git_revision")
        assert result.has_next()
        assert result.get_next()[0] == "abc"

    def test_embedding_column_exists(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        db = lb.Database(db_path)
        conn = lb.Connection(db)
        # Verify the embedding column exists by setting it.
        conn.execute("CREATE (c:Concept {id: 'emb_test', name: 'EmbTest'})")
        # Just confirm the column is queryable (will be null).
        result = conn.execute("MATCH (c:Concept {id: 'emb_test'}) RETURN c.embedding")
        assert result.has_next()

    def test_relationship_tables_created(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        db = lb.Database(db_path)
        conn = lb.Connection(db)
        # Create two concepts and link them with PartOf.
        conn.execute("CREATE (c:Concept {id: 'parent', name: 'Parent'})")
        conn.execute("CREATE (c:Concept {id: 'child', name: 'Child'})")
        conn.execute(
            "MATCH (a:Concept {id: 'child'}), (b:Concept {id: 'parent'}) "
            "CREATE (a)-[:PartOf {description: 'child of parent'}]->(b)"
        )
        result = conn.execute("MATCH (a:Concept)-[:PartOf]->(b:Concept) RETURN a.id, b.id")
        assert result.has_next()
        row = result.get_next()
        assert row[0] == "child"
        assert row[1] == "parent"

"""Tests for theo.tools.upsert_node and theo.tools.upsert_rel."""

from __future__ import annotations

import pytest
import real_ladybug as lb

from theo.tools.upsert_node import upsert_node
from theo.tools.upsert_rel import upsert_rel


class TestUpsertNode:
    """Test node upsert operations."""

    def test_upsert_concept(self, fresh_db: str) -> None:
        result = upsert_node(
            fresh_db,
            "Concept",
            {"id": "test-concept", "name": "Test Concept", "description": "A test"},
        )
        assert result["status"] == "ok"
        assert result["table"] == "Concept"
        assert result["key"] == "test-concept"

        # Verify it was created.
        db = lb.Database(fresh_db, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute("MATCH (c:Concept {id: 'test-concept'}) RETURN c.name")
        assert r.has_next()
        assert r.get_next()[0] == "Test Concept"

    def test_upsert_sourcefile(self, fresh_db: str) -> None:
        result = upsert_node(
            fresh_db,
            "SourceFile",
            {"path": "src/main.py", "name": "main.py", "language": "python"},
        )
        assert result["status"] == "ok"
        assert result["key"] == "src/main.py"

    def test_upsert_updates_existing_node(self, fresh_db: str) -> None:
        upsert_node(
            fresh_db,
            "Concept",
            {"id": "c1", "name": "Original", "description": "First version"},
        )
        upsert_node(
            fresh_db,
            "Concept",
            {"id": "c1", "name": "Updated", "description": "Second version"},
        )

        db = lb.Database(fresh_db, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute("MATCH (c:Concept {id: 'c1'}) RETURN c.name, c.description")
        assert r.has_next()
        row = r.get_next()
        assert row[0] == "Updated"
        assert row[1] == "Second version"

    def test_upsert_with_git_revision(self, fresh_db: str) -> None:
        upsert_node(
            fresh_db,
            "Concept",
            {"id": "rev-test", "name": "RevTest", "git_revision": "abc123"},
        )
        db = lb.Database(fresh_db, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute("MATCH (c:Concept {id: 'rev-test'}) RETURN c.git_revision")
        assert r.has_next()
        assert r.get_next()[0] == "abc123"

    def test_upsert_primary_key_only(self, fresh_db: str) -> None:
        result = upsert_node(fresh_db, "Concept", {"id": "minimal"})
        assert result["status"] == "ok"

    def test_invalid_table_raises(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Invalid table"):
            upsert_node(fresh_db, "NonExistent", {"id": "x"})

    def test_invalid_field_name_raises(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Unknown field"):
            upsert_node(fresh_db, "Concept", {"id": "x", "bad field!": "v"})

    def test_unknown_field_raises(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Unknown field"):
            upsert_node(fresh_db, "Concept", {"id": "x", "banana": 42})

    def test_embedding_field_rejected(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Unknown field"):
            upsert_node(fresh_db, "Concept", {"id": "x", "embedding": [0.1] * 768})

    def test_missing_pk_raises(self, fresh_db: str) -> None:
        with pytest.raises(KeyError):
            upsert_node(fresh_db, "Concept", {"name": "NoPK"})


class TestUpsertRel:
    """Test relationship upsert operations."""

    def test_upsert_depends_on(self, fresh_db: str) -> None:
        # Create two concepts first.
        upsert_node(fresh_db, "Concept", {"id": "a", "name": "A"})
        upsert_node(fresh_db, "Concept", {"id": "b", "name": "B"})

        result = upsert_rel(
            fresh_db,
            "DependsOn",
            "Concept",
            "a",
            "Concept",
            "b",
            properties={"description": "A depends on B"},
        )
        assert result["status"] == "ok"
        assert result["rel_type"] == "DependsOn"

        # Verify.
        db = lb.Database(fresh_db, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute(
            "MATCH (a:Concept)-[r:DependsOn]->(b:Concept) RETURN a.id, b.id, r.description"
        )
        assert r.has_next()
        row = r.get_next()
        assert row[0] == "a"
        assert row[1] == "b"
        assert row[2] == "A depends on B"

    def test_upsert_belongs_to(self, fresh_db: str) -> None:
        upsert_node(fresh_db, "SourceFile", {"path": "x.py", "name": "x.py"})
        upsert_node(fresh_db, "Concept", {"id": "mod", "name": "Module"})

        result = upsert_rel(
            fresh_db,
            "BelongsTo",
            "SourceFile",
            "x.py",
            "Concept",
            "mod",
        )
        assert result["status"] == "ok"

    def test_upsert_imports(self, fresh_db: str) -> None:
        upsert_node(fresh_db, "SourceFile", {"path": "a.py", "name": "a.py"})
        upsert_node(fresh_db, "SourceFile", {"path": "b.py", "name": "b.py"})

        result = upsert_rel(
            fresh_db,
            "Imports",
            "SourceFile",
            "a.py",
            "SourceFile",
            "b.py",
            properties={"description": "a imports b"},
        )
        assert result["status"] == "ok"

    def test_upsert_interacts_with(self, fresh_db: str) -> None:
        upsert_node(fresh_db, "Concept", {"id": "x", "name": "X"})
        upsert_node(fresh_db, "Concept", {"id": "y", "name": "Y"})

        result = upsert_rel(
            fresh_db,
            "InteractsWith",
            "Concept",
            "x",
            "Concept",
            "y",
        )
        assert result["status"] == "ok"

    def test_upsert_part_of(self, fresh_db: str) -> None:
        upsert_node(fresh_db, "Concept", {"id": "child", "name": "Child"})
        upsert_node(fresh_db, "Concept", {"id": "parent", "name": "Parent"})

        result = upsert_rel(
            fresh_db,
            "PartOf",
            "Concept",
            "child",
            "Concept",
            "parent",
        )
        assert result["status"] == "ok"

    def test_upsert_rel_updates_properties(self, fresh_db: str) -> None:
        upsert_node(fresh_db, "Concept", {"id": "p", "name": "P"})
        upsert_node(fresh_db, "Concept", {"id": "q", "name": "Q"})

        upsert_rel(
            fresh_db,
            "DependsOn",
            "Concept",
            "p",
            "Concept",
            "q",
            properties={"description": "v1"},
        )
        upsert_rel(
            fresh_db,
            "DependsOn",
            "Concept",
            "p",
            "Concept",
            "q",
            properties={"description": "v2"},
        )

        db = lb.Database(fresh_db, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute(
            "MATCH (a:Concept {id: 'p'})-[r:DependsOn]->(b:Concept {id: 'q'}) RETURN r.description"
        )
        assert r.has_next()
        assert r.get_next()[0] == "v2"

    def test_invalid_rel_type_raises(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Invalid rel_type"):
            upsert_rel(fresh_db, "FakeRel", "Concept", "a", "Concept", "b")

    def test_invalid_from_table_raises(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Invalid from_table"):
            upsert_rel(fresh_db, "DependsOn", "Fake", "a", "Concept", "b")

    def test_invalid_to_table_raises(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Invalid to_table"):
            upsert_rel(fresh_db, "DependsOn", "Concept", "a", "Fake", "b")

    def test_invalid_property_name_raises(self, fresh_db: str) -> None:
        with pytest.raises(ValueError, match="Invalid field name"):
            upsert_rel(
                fresh_db,
                "DependsOn",
                "Concept",
                "a",
                "Concept",
                "b",
                properties={"bad field!": "x"},
            )

    def test_upsert_rel_no_properties(self, fresh_db: str) -> None:
        upsert_node(fresh_db, "Concept", {"id": "n1", "name": "N1"})
        upsert_node(fresh_db, "Concept", {"id": "n2", "name": "N2"})
        result = upsert_rel(
            fresh_db,
            "DependsOn",
            "Concept",
            "n1",
            "Concept",
            "n2",
        )
        assert result["status"] == "ok"

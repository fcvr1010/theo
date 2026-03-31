"""Tests for theo.graph.query."""

from __future__ import annotations

import pytest

from theo.graph.query import query


class TestQuery:
    """Test read-only Cypher query execution."""

    def test_query_returns_results(self, populated_db: str) -> None:
        rows = query(populated_db, "MATCH (c:Concept) RETURN c.id, c.name ORDER BY c.id")
        assert len(rows) == 3
        ids = [r["c.id"] for r in rows]
        assert "dispatch" in ids
        assert "delivery" in ids
        assert "config" in ids

    def test_query_with_filter(self, populated_db: str) -> None:
        rows = query(
            populated_db,
            "MATCH (c:Concept) WHERE c.id = 'dispatch' RETURN c.name",
        )
        assert len(rows) == 1
        assert rows[0]["c.name"] == "Dispatch"

    def test_query_empty_result(self, populated_db: str) -> None:
        rows = query(
            populated_db,
            "MATCH (c:Concept) WHERE c.id = 'nonexistent' RETURN c.name",
        )
        assert rows == []

    def test_query_relationships(self, populated_db: str) -> None:
        rows = query(
            populated_db,
            "MATCH (a:Concept)-[:DependsOn]->(b:Concept) RETURN a.id, b.id",
        )
        assert len(rows) == 1
        assert rows[0]["a.id"] == "dispatch"
        assert rows[0]["b.id"] == "delivery"

    def test_query_source_files(self, populated_db: str) -> None:
        rows = query(populated_db, "MATCH (f:SourceFile) RETURN f.path ORDER BY f.path")
        assert len(rows) == 2

    def test_query_symbols(self, populated_db: str) -> None:
        rows = query(populated_db, "MATCH (s:Symbol) RETURN s.id, s.name")
        assert len(rows) == 1
        assert rows[0]["s.name"] == "classify"

    def test_query_rejects_create(self, populated_db: str) -> None:
        with pytest.raises(ValueError, match="Only read-only queries"):
            query(populated_db, "CREATE (c:Concept {id: 'evil'})")

    def test_query_rejects_merge(self, populated_db: str) -> None:
        with pytest.raises(ValueError, match="Only read-only queries"):
            query(populated_db, "MERGE (c:Concept {id: 'evil'})")

    def test_query_rejects_delete(self, populated_db: str) -> None:
        with pytest.raises(ValueError, match="Only read-only queries"):
            query(populated_db, "MATCH (c:Concept) DELETE c")

    def test_query_rejects_set(self, populated_db: str) -> None:
        with pytest.raises(ValueError, match="Only read-only queries"):
            query(
                populated_db,
                "MATCH (c:Concept {id: 'dispatch'}) SET c.name = 'hacked'",
            )

    def test_query_rejects_drop(self, populated_db: str) -> None:
        with pytest.raises(ValueError, match="Only read-only queries"):
            query(populated_db, "DROP TABLE Concept")

    def test_query_git_revision(self, populated_db: str) -> None:
        rows = query(
            populated_db,
            "MATCH (c:Concept {id: 'dispatch'}) RETURN c.git_revision",
        )
        assert len(rows) == 1
        assert rows[0]["c.git_revision"] == "abc123"

    def test_query_across_relationship_chain(self, populated_db: str) -> None:
        rows = query(
            populated_db,
            "MATCH (s:Symbol)-[:DefinedIn]->(f:SourceFile)-[:BelongsTo]->(c:Concept) "
            "RETURN s.name, f.path, c.name",
        )
        assert len(rows) == 1
        assert rows[0]["s.name"] == "classify"
        assert rows[0]["f.path"] == "src/dispatch.py"
        assert rows[0]["c.name"] == "Dispatch"

    def test_query_count(self, populated_db: str) -> None:
        rows = query(populated_db, "MATCH (c:Concept) RETURN count(c) AS cnt")
        assert rows[0]["cnt"] == 3

    def test_query_on_empty_db(self, fresh_db: str) -> None:
        rows = query(fresh_db, "MATCH (c:Concept) RETURN c.id")
        assert rows == []

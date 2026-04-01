"""Tests for theo.tools.query -- write-path query tool."""

from __future__ import annotations

import pytest

from theo.tools.query import query


class TestToolsQuery:
    """Test direct-path Cypher query execution."""

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

    def test_query_count(self, populated_db: str) -> None:
        rows = query(populated_db, "MATCH (c:Concept) RETURN count(c) AS cnt")
        assert rows[0]["cnt"] == 3

    def test_query_on_empty_db(self, fresh_db: str) -> None:
        rows = query(fresh_db, "MATCH (c:Concept) RETURN c.id")
        assert rows == []

    def test_query_read_only_default(self, populated_db: str) -> None:
        """Verify default read_only=True prevents mutations."""
        with pytest.raises(RuntimeError):
            query(populated_db, "CREATE (c:Concept {id: 'test'})")

    def test_query_read_write_mode(self, fresh_db: str) -> None:
        """Verify read_only=False allows mutations."""
        query(
            fresh_db,
            "CREATE (c:Concept {id: 'rw-test', name: 'RW Test', level: 0, "
            "kind: 'root', description: 'test', notes: 'test', git_revision: 'abc'})",
            read_only=False,
        )
        rows = query(fresh_db, "MATCH (c:Concept {id: 'rw-test'}) RETURN c.name")
        assert len(rows) == 1
        assert rows[0]["c.name"] == "RW Test"

    def test_query_git_revision(self, populated_db: str) -> None:
        rows = query(
            populated_db,
            "MATCH (c:Concept {id: 'dispatch'}) RETURN c.git_revision",
        )
        assert len(rows) == 1
        assert rows[0]["c.git_revision"] == "abc123"

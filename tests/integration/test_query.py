"""Integration tests for theo.client.query (real DB, repo-based API)."""

from __future__ import annotations

import pytest

from theo.client.query import query


@pytest.mark.integration
class TestQueryIntegration:
    """Integration tests exercising the query client against a real KuzuDB."""

    def test_query_concepts(self, populated_repo: str) -> None:
        rows = query(populated_repo, "MATCH (c:Concept) RETURN c.id ORDER BY c.id")
        ids = [r["c.id"] for r in rows]
        assert ids == ["config", "delivery", "dispatch"]

    def test_query_relationships(self, populated_repo: str) -> None:
        rows = query(
            populated_repo,
            "MATCH (a:Concept)-[:DependsOn]->(b:Concept) RETURN a.id AS src, b.id AS dst",
        )
        assert len(rows) == 1
        assert rows[0]["src"] == "dispatch"
        assert rows[0]["dst"] == "delivery"

    def test_query_cross_table_traversal(self, populated_repo: str) -> None:
        """Traverse from SourceFile through BelongsTo to Concept and then DependsOn."""
        rows = query(
            populated_repo,
            "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept)-[:DependsOn]->(d:Concept) "
            "RETURN f.path AS file, c.name AS concept, d.name AS dependency",
        )
        assert len(rows) == 1
        assert rows[0]["file"] == "src/dispatch.py"
        assert rows[0]["concept"] == "Dispatch"
        assert rows[0]["dependency"] == "Delivery"

    def test_query_imports(self, populated_repo: str) -> None:
        rows = query(
            populated_repo,
            "MATCH (a:SourceFile)-[:Imports]->(b:SourceFile) "
            "RETURN a.path AS importer, b.path AS imported",
        )
        assert len(rows) == 1
        assert rows[0]["importer"] == "src/dispatch.py"
        assert rows[0]["imported"] == "src/delivery.py"

    def test_query_aggregation(self, populated_repo: str) -> None:
        rows = query(
            populated_repo,
            "MATCH (c:Concept) RETURN c.level AS level, count(*) AS cnt ORDER BY level",
        )
        assert len(rows) == 2
        assert rows[0]["level"] == 1
        assert rows[0]["cnt"] == 2
        assert rows[1]["level"] == 2
        assert rows[1]["cnt"] == 1

    def test_query_empty_db(self, fresh_repo: str) -> None:
        rows = query(fresh_repo, "MATCH (c:Concept) RETURN c.id")
        assert rows == []

    def test_query_rejects_mutation(self, fresh_repo: str) -> None:
        with pytest.raises(ValueError, match="Only read-only queries"):
            query(fresh_repo, "CREATE (c:Concept {id: 'evil'})")

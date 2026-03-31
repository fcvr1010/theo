"""Tests for theo.client.semantic_search (integration -- requires model download)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestSemanticSearch:
    """Integration tests for semantic search."""

    def test_search_empty_db(self, fresh_db: str) -> None:
        from theo.client.semantic_search import semantic_search

        result = semantic_search(fresh_db, "test query")
        assert result["matches"] == []

    def test_search_returns_matches(self, populated_db: str) -> None:
        import real_ladybug as lb

        from theo._embed import embed_text
        from theo.client.semantic_search import semantic_search

        # Add embeddings to nodes first.
        db = lb.Database(populated_db)
        conn = lb.Connection(db)

        vecs = embed_text(
            [
                "Message dispatching",
                "Message delivery pipeline",
                "Configuration management",
            ]
        )
        for concept_id, vec in zip(
            ["dispatch", "delivery", "config"],
            vecs,
            strict=True,
        ):
            conn.execute(
                f"MATCH (c:Concept {{id: '{concept_id}'}}) SET c.embedding = $emb",
                {"emb": vec},
            )
        del conn
        db.close()

        result = semantic_search(
            populated_db,
            "how does message dispatching work?",
            top_k=3,
        )
        assert len(result["matches"]) > 0
        # dispatch should be the top match.
        assert result["matches"][0]["id"] == "dispatch"

    def test_search_with_table_filter(self, populated_db: str) -> None:
        import real_ladybug as lb

        from theo._embed import embed_text
        from theo.client.semantic_search import semantic_search

        db = lb.Database(populated_db)
        conn = lb.Connection(db)
        vecs = embed_text(["Dispatcher implementation", "Delivery pipeline"])
        for path, vec in zip(
            ["src/dispatch.py", "src/delivery.py"],
            vecs,
            strict=True,
        ):
            conn.execute(
                f"MATCH (f:SourceFile {{path: '{path}'}}) SET f.embedding = $emb",
                {"emb": vec},
            )
        del conn
        db.close()

        result = semantic_search(
            populated_db,
            "dispatcher",
            table="SourceFile",
            top_k=5,
        )
        assert all(m["table"] == "SourceFile" for m in result["matches"])

    def test_search_invalid_table_raises(self, fresh_db: str) -> None:
        from theo.client.semantic_search import semantic_search

        with pytest.raises(ValueError, match="Invalid table"):
            semantic_search(fresh_db, "test", table="NonExistent")

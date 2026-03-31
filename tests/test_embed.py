"""Tests for theo.graph.embed_text (integration -- requires model download)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestEmbedText:
    """Integration tests for embedding generation."""

    def test_embed_single_text(self) -> None:
        from theo.graph._schema import EMBEDDING_DIM
        from theo.graph.embed_text import embed_text

        result = embed_text(["hello world"])
        assert len(result) == 1
        assert len(result[0]) == EMBEDDING_DIM

    def test_embed_batch(self) -> None:
        from theo.graph.embed_text import embed_text

        result = embed_text(["first", "second", "third"])
        assert len(result) == 3

    def test_embed_empty_list(self) -> None:
        from theo.graph.embed_text import embed_text

        result = embed_text([])
        assert result == []

    def test_embed_query(self) -> None:
        from theo.graph._schema import EMBEDDING_DIM
        from theo.graph.embed_text import embed_query

        result = embed_query("what is dispatch?")
        assert len(result) == EMBEDDING_DIM

    def test_embed_returns_floats(self) -> None:
        from theo.graph.embed_text import embed_text

        result = embed_text(["test"])
        assert all(isinstance(v, float) for v in result[0])

    def test_different_prefixes_produce_different_embeddings(self) -> None:
        from theo.graph.embed_text import embed_text

        doc = embed_text(["test text"], prefix="search_document")[0]
        query = embed_text(["test text"], prefix="search_query")[0]
        # They should be different (different prefixes).
        assert doc != query

    def test_reset_model(self) -> None:
        from theo.graph.embed_text import embed_text, reset_model

        embed_text(["trigger load"])
        reset_model()
        from theo.graph import embed_text as et_mod

        assert et_mod._model is None

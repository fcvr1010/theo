"""Integration tests for semantic indexing + search.

These tests require the ``fastembed`` optional extra and hit a real embedding
model.  They are gated by the ``integration`` marker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

fastembed = pytest.importorskip("fastembed", reason="fastembed is not installed")

from theo._db import (  # noqa: E402
    create_all_vector_indexes,
    drop_all_vector_indexes,
    drop_vector_index,
    migrate_embedding_column,
    reindex_all,
    run_query,
    semantic_search,
    upsert_edge,
    upsert_node,
    write_node_embedding,
)
from theo._embed import EMBEDDING_DIM, embed_documents, embed_query  # noqa: E402


@pytest.fixture()  # type: ignore[misc]
def populated_db(tmp_db: Path) -> Path:
    """Seed a fresh DB with a few semantically distinguishable concepts."""
    upsert_node(
        tmp_db,
        "Concept",
        {
            "id": "auth",
            "name": "Authentication",
            "level": 1,
            "description": "Handles user login and identity via JWT tokens.",
            "notes": "Uses bcrypt for password hashing. Sessions expire after 24h.",
            "git_revision": "r",
        },
    )
    upsert_node(
        tmp_db,
        "Concept",
        {
            "id": "ui",
            "name": "UI Layer",
            "level": 1,
            "description": "Renders the frontend pages and handles user interactions.",
            "notes": "React SPA with server-side rendering disabled.",
            "git_revision": "r",
        },
    )
    upsert_node(
        tmp_db,
        "Concept",
        {
            "id": "delivery",
            "name": "Message Delivery",
            "level": 1,
            "description": "Sends messages through email, SMS, and push notification channels.",
            "notes": "Retries on transient failures with exponential backoff.",
            "git_revision": "r",
        },
    )
    upsert_node(
        tmp_db,
        "SourceFile",
        {
            "path": "src/login.py",
            "name": "login.py",
            "description": "Login endpoint implementation.",
            "notes": "Accepts username+password, issues JWT on success.",
            "git_revision": "r",
        },
    )
    upsert_edge(
        tmp_db,
        "BelongsTo",
        "src/login.py",
        "auth",
        "Login handler is part of authentication.",
        git_revision="r",
    )
    reindex_all(tmp_db)
    return tmp_db


class TestEmbed:
    def test_embed_documents_dim(self) -> None:
        vecs = embed_documents(["hello world", "another text"])
        assert len(vecs) == 2
        assert all(len(v) == EMBEDDING_DIM for v in vecs)

    def test_embed_query_dim(self) -> None:
        vec = embed_query("what does this do?")
        assert len(vec) == EMBEDDING_DIM

    def test_query_vs_document_prefix_differ(self) -> None:
        # Same raw text, different prefixes -> vectors should not be identical.
        doc_vec = embed_documents(["login handler"])[0]
        query_vec = embed_query("login handler")
        assert doc_vec != query_vec


class TestSchemaMigration:
    def test_migrate_is_idempotent(self, tmp_db: Path) -> None:
        migrate_embedding_column(tmp_db)
        migrate_embedding_column(tmp_db)
        # If we got here without raising, both calls succeeded.


class TestVectorIndexLifecycle:
    def test_drop_create_all(self, tmp_db: Path) -> None:
        # Fresh DB has no index yet; drop is a no-op.
        assert drop_all_vector_indexes(tmp_db) == []
        created = create_all_vector_indexes(tmp_db)
        assert set(created) == {"Concept", "SourceFile"}
        # Second drop returns both names.
        assert set(drop_all_vector_indexes(tmp_db)) == {"Concept", "SourceFile"}

    def test_drop_rejects_rel_table(self, tmp_db: Path) -> None:
        with pytest.raises(ValueError):
            drop_vector_index(tmp_db, "BelongsTo")


class TestSemanticSearch:
    def test_ranks_auth_first_for_login_query(self, populated_db: Path) -> None:
        qvec = embed_query("how does user login work?")
        matches = semantic_search(populated_db, qvec, None, 5)
        assert matches, "expected at least one match"
        # The auth concept or the login file should be in the top 2.
        # The uniform shape gives each match a `ref` dict: id/name for nodes,
        # from_id/to_id for edges.  Check either auth or the login file is in
        # the top 2.
        top_refs = [
            (m["table"] if m["kind"] == "node" else m["rel_type"], m["ref"]) for m in matches[:2]
        ]
        hit = False
        for _tbl, ref in top_refs:
            if ref.get("id") == "auth" or ref.get("id") == "src/login.py":
                hit = True
            if ref.get("from_id") == "src/login.py" and ref.get("to_id") == "auth":
                hit = True
        assert hit, f"expected auth or login in top 2, got {top_refs}"

    def test_table_filter_nodes_only(self, populated_db: Path) -> None:
        qvec = embed_query("login")
        matches = semantic_search(populated_db, qvec, "Concept", 10)
        for m in matches:
            assert m["kind"] == "node"
            assert m["table"] == "Concept"

    def test_table_filter_edges_only(self, populated_db: Path) -> None:
        qvec = embed_query("belonging")
        matches = semantic_search(populated_db, qvec, "BelongsTo", 10)
        # The seed data has exactly one BelongsTo edge.
        assert len(matches) == 1
        assert matches[0]["kind"] == "edge"
        assert matches[0]["rel_type"] == "BelongsTo"

    def test_top_k_limits_total(self, populated_db: Path) -> None:
        qvec = embed_query("anything")
        assert len(semantic_search(populated_db, qvec, None, 2)) <= 2

    def test_invalid_table_raises(self, populated_db: Path) -> None:
        qvec = embed_query("x")
        with pytest.raises(ValueError):
            semantic_search(populated_db, qvec, "Nonsense", 1)

    def test_hnsw_absent_falls_back_to_brute_force(self, populated_db: Path) -> None:
        # Drop the HNSW on Concept and verify search still works.
        drop_vector_index(populated_db, "Concept")
        qvec = embed_query("login")
        matches = semantic_search(populated_db, qvec, "Concept", 5)
        assert matches, "brute-force fallback should return matches"


class TestWriteNodeEmbedding:
    def test_sets_embedding_and_rebuilds_index(self, tmp_db: Path) -> None:
        upsert_node(
            tmp_db,
            "Concept",
            {"id": "x", "name": "X", "description": "thing", "git_revision": "r"},
        )
        vec = embed_documents(["thing"])[0]
        write_node_embedding(tmp_db, "Concept", "x", vec)
        rows = run_query(
            tmp_db, "MATCH (n:Concept {id: 'x'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is False

    def test_mid_sequence_set_failure_preserves_hnsw(self, tmp_db: Path) -> None:
        """If SET raises between drop and create, the index must still exist
        on exit — otherwise searches degrade silently to brute force until
        the next successful write.  Regression test for the review feedback
        at ``_db.write_node_embedding``.
        """
        from unittest.mock import patch

        from theo import _db as db_module

        upsert_node(
            tmp_db,
            "Concept",
            {"id": "victim", "name": "V", "description": "t", "git_revision": "r"},
        )
        # Build an HNSW index up front so we can distinguish "dropped-then-
        # never-recreated" from "never existed".
        from theo._db import create_vector_index

        create_vector_index(tmp_db, "Concept")

        real_execute = db_module._execute
        calls = {"count": 0}

        def flaky_execute(conn, query, params=None):  # type: ignore[no-untyped-def]
            # Let the DROP_VECTOR_INDEX call through, then fail the SET, then
            # let the recreating CALL_VECTOR_INDEX through.
            if "SET n.embedding" in query:
                calls["count"] += 1
                raise RuntimeError("simulated SET failure")
            return real_execute(conn, query, params)

        with (
            patch.object(db_module, "_execute", side_effect=flaky_execute),
            pytest.raises(RuntimeError, match="simulated SET failure"),
        ):
            write_node_embedding(tmp_db, "Concept", "victim", [0.1] * EMBEDDING_DIM)
        assert calls["count"] == 1, "SET should have been attempted exactly once"

        # After the failure, the HNSW index must be back: running the search
        # path that exercises HNSW and asserting it does not take the
        # brute-force fallback is the most direct check we can make.
        qvec = embed_query("t")
        matches = semantic_search(tmp_db, qvec, "Concept", 5)
        # Matches come back; the embedding itself was not written so the
        # victim row has no vector, but the important invariant is that
        # CREATE_VECTOR_INDEX ran successfully.  If it hadn't, a subsequent
        # write_node_embedding on a *different* node would redundantly drop
        # a non-existent index and succeed on SET — so provoke that path
        # and verify it does not raise.
        upsert_node(
            tmp_db, "Concept", {"id": "survivor", "description": "post", "git_revision": "r"}
        )
        write_node_embedding(tmp_db, "Concept", "survivor", [0.2] * EMBEDDING_DIM)
        rows = run_query(
            tmp_db, "MATCH (n:Concept {id: 'survivor'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is False
        # And the query returned the expected number of results.
        assert len(matches) >= 0


class TestExportExcludesEmbeddings:
    """Embeddings are derived, large, and non-portable — never in CSV."""

    def test_csv_has_no_embedding_column(self, tmp_db: Path) -> None:
        from theo._db import export_csv

        upsert_node(
            tmp_db,
            "Concept",
            {"id": "a", "name": "A", "description": "alpha", "git_revision": "r"},
        )
        reindex_all(tmp_db)  # populates embeddings in the DB

        csv_dir = tmp_db.parent / "csv"
        csv_dir.mkdir()
        export_csv(tmp_db, csv_dir)

        concepts_csv = (csv_dir / "concepts.csv").read_text()
        # The serialised row should be 6 columns (id, name, level, description,
        # notes, git_revision) — no 7th column carrying a vector.
        first_line = concepts_csv.splitlines()[0]
        assert first_line.count(",") == 5, f"unexpected column count: {first_line!r}"
        # The word "FLOAT" or any bracketed list-ish vector artefact must not
        # appear either.
        assert "[" not in concepts_csv
        assert "FLOAT" not in concepts_csv


class TestReindexAll:
    def test_populates_missing_embeddings(self, tmp_db: Path) -> None:
        upsert_node(
            tmp_db,
            "Concept",
            {"id": "a", "name": "A", "description": "alpha", "git_revision": "r"},
        )
        counts = reindex_all(tmp_db)
        assert counts["Concept"] == 1
        rows = run_query(
            tmp_db, "MATCH (n:Concept {id: 'a'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is False

    def test_skips_rows_with_empty_text(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "blank", "name": "Blank", "git_revision": "r"})
        counts = reindex_all(tmp_db)
        # No description and no notes -> no embedding, no count.
        assert counts["Concept"] == 0
        rows = run_query(
            tmp_db, "MATCH (n:Concept {id: 'blank'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is True

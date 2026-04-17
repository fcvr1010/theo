"""Integration tests for serve.py tool handlers (called directly, not via MCP)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import click
import pytest

from theo._db import export_csv, run_query, upsert_edge, upsert_node
from theo.cli.serve import (
    _ensure_db,
    handle_theo_delete_edge,
    handle_theo_delete_node,
    handle_theo_query,
    handle_theo_reload,
    handle_theo_search,
    handle_theo_stats,
    handle_theo_upsert_edge,
    handle_theo_upsert_node,
)


class TestHandleTheoStats:
    def test_returns_correct_structure(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        config_path = tmp_theo_project / ".theo" / "config.json"

        with patch("theo.cli.serve.head_commit", return_value="abc123"):
            result = handle_theo_stats(db_path, csv_dir, config_path)

        assert "node_counts" in result
        assert "edge_counts" in result
        assert "last_indexed_commit" in result
        assert "head_commit" in result
        assert "is_stale" in result

    def test_is_stale_when_no_indexed_commit(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        config_path = tmp_theo_project / ".theo" / "config.json"

        with patch("theo.cli.serve.head_commit", return_value="abc123"):
            result = handle_theo_stats(db_path, csv_dir, config_path)

        assert result["is_stale"] is True

    def test_not_stale_when_matching(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        config_path = tmp_theo_project / ".theo" / "config.json"
        # Write last_indexed_commit to disk so handle_theo_stats reads it
        config = json.loads(config_path.read_text())
        config["last_indexed_commit"] = "abc123"
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        with patch("theo.cli.serve.head_commit", return_value="abc123"):
            result = handle_theo_stats(db_path, csv_dir, config_path)

        assert result["is_stale"] is False


class TestHandleTheoQuery:
    def test_executes_cypher(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        upsert_node(db_path, "Concept", {"id": "test", "name": "Test"})
        rows = handle_theo_query(db_path, "MATCH (n:Concept) RETURN n.id, n.name")
        assert len(rows) == 1
        assert rows[0]["n.id"] == "test"


class TestHandleTheoUpsertNode:
    def test_creates_node_and_exports_csv(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        result = handle_theo_upsert_node(
            db_path,
            csv_dir,
            "Concept",
            {"id": "new", "name": "New Concept"},
        )
        assert result["status"] == "ok"
        assert result["id"] == "new"

        # Verify CSV was exported
        csv_content = (csv_dir / "concepts.csv").read_text()
        assert "new" in csv_content

    def test_invalid_table_returns_error(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        result = handle_theo_upsert_node(db_path, csv_dir, "Bogus", {"id": "x"})
        assert result["status"] == "error"

    def test_missing_pk_returns_error(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        result = handle_theo_upsert_node(db_path, csv_dir, "Concept", {"name": "no id"})
        assert result["status"] == "error"


class TestHandleTheoUpsertEdge:
    def test_creates_edge_and_exports_csv(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        upsert_node(db_path, "Concept", {"id": "a"})
        upsert_node(db_path, "Concept", {"id": "b"})
        result = handle_theo_upsert_edge(
            db_path,
            csv_dir,
            "PartOf",
            "a",
            "b",
            "link",
            git_revision="abc123",
        )
        assert result["status"] == "ok"

    def test_missing_endpoints_returns_error(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        result = handle_theo_upsert_edge(
            db_path,
            csv_dir,
            "PartOf",
            "missing",
            "also_missing",
            git_revision="abc123",
        )
        assert result["status"] == "error"

    def test_invalid_rel_type_returns_error(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        result = handle_theo_upsert_edge(
            db_path,
            csv_dir,
            "Bogus",
            "a",
            "b",
            git_revision="abc123",
        )
        assert result["status"] == "error"


class TestHandleTheoDeleteNode:
    def test_deletes_node_and_updates_csv(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        upsert_node(db_path, "Concept", {"id": "doomed", "name": "Doomed"})
        # Prime CSV so we can verify it shrinks after deletion.
        handle_theo_upsert_node(db_path, csv_dir, "Concept", {"id": "doomed", "name": "Doomed"})
        assert "doomed" in (csv_dir / "concepts.csv").read_text()

        result = handle_theo_delete_node(db_path, csv_dir, "Concept", "doomed")
        assert result["status"] == "ok"
        assert "doomed" not in (csv_dir / "concepts.csv").read_text()

    def test_invalid_table_returns_error(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        result = handle_theo_delete_node(db_path, csv_dir, "Bogus", "x")
        assert result["status"] == "error"

    def test_refuses_without_detach_when_edges_exist(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        upsert_node(db_path, "SourceFile", {"path": "a.py"})
        upsert_node(db_path, "SourceFile", {"path": "b.py"})
        upsert_edge(db_path, "Imports", "a.py", "b.py", git_revision="r1")

        result = handle_theo_delete_node(db_path, csv_dir, "SourceFile", "a.py")
        assert result["status"] == "error"

        # Node must still be there after the refused delete.
        rows = run_query(db_path, "MATCH (n:SourceFile {path: 'a.py'}) RETURN count(n) AS c")
        assert rows[0]["c"] == 1

    def test_detach_true_succeeds(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        upsert_node(db_path, "SourceFile", {"path": "a.py"})
        upsert_node(db_path, "SourceFile", {"path": "b.py"})
        upsert_edge(db_path, "Imports", "a.py", "b.py", git_revision="r1")

        result = handle_theo_delete_node(db_path, csv_dir, "SourceFile", "a.py", detach=True)
        assert result["status"] == "ok"


class TestHandleTheoDeleteEdge:
    def test_deletes_edge_and_updates_csv(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        upsert_node(db_path, "Concept", {"id": "a"})
        upsert_node(db_path, "Concept", {"id": "b"})
        handle_theo_upsert_edge(db_path, csv_dir, "PartOf", "a", "b", "link", git_revision="r1")
        assert "link" in (csv_dir / "part_of.csv").read_text()

        result = handle_theo_delete_edge(db_path, csv_dir, "PartOf", "a", "b")
        assert result["status"] == "ok"
        assert (csv_dir / "part_of.csv").read_text().strip() == ""

    def test_invalid_rel_type_returns_error(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        result = handle_theo_delete_edge(db_path, csv_dir, "Bogus", "a", "b")
        assert result["status"] == "error"

    def test_missing_edge_returns_error(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        upsert_node(db_path, "Concept", {"id": "a"})
        upsert_node(db_path, "Concept", {"id": "b"})
        result = handle_theo_delete_edge(db_path, csv_dir, "PartOf", "a", "b")
        assert result["status"] == "error"


class TestEnsureDb:
    def test_rebuilds_from_csv_when_db_missing(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"

        # Populate DB, export CSVs, then delete DB
        upsert_node(db_path, "Concept", {"id": "surv", "name": "Survivor"})
        upsert_node(db_path, "Concept", {"id": "other"})
        upsert_edge(db_path, "PartOf", "surv", "other", git_revision="r1")
        from theo._db import export_csv

        export_csv(db_path, csv_dir)
        db_path.unlink()

        _ensure_db(db_path, csv_dir)

        assert db_path.exists()
        rows = run_query(db_path, "MATCH (n:Concept {id: 'surv'}) RETURN n.name")
        assert rows[0]["n.name"] == "Survivor"

    def test_exits_when_no_db_and_no_csvs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "db" / "theo.db"
        csv_dir = tmp_path / "csv"
        csv_dir.mkdir(parents=True)
        with pytest.raises(click.exceptions.Exit):
            _ensure_db(db_path, csv_dir)

    def test_does_not_rebuild_when_db_exists(self, tmp_theo_project: Path) -> None:
        # The fixture's fresh DB has the embedding column via DDL, so the
        # idempotent migration inside _ensure_db is a no-op, but it still
        # opens a connection which bumps mtime.  What we actually care about
        # is that _ensure_db does NOT re-run ``rebuild_from_csv`` (that would
        # wipe any runtime state).  Check that by seeding a marker Concept
        # via the DB directly and verifying it survives the call.
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"

        upsert_node(
            db_path,
            "Concept",
            {"id": "survivor", "name": "Survivor", "git_revision": "abc"},
        )
        _ensure_db(db_path, csv_dir)
        rows = run_query(db_path, "MATCH (n:Concept {id: 'survivor'}) RETURN n.name")
        assert rows and rows[0]["n.name"] == "Survivor"


@pytest.mark.integration
class TestHandleTheoSearch:
    def _seed(self, db_path: Path, csv_dir: Path) -> None:
        handle_theo_upsert_node(
            db_path,
            csv_dir,
            "Concept",
            {
                "id": "auth",
                "name": "Auth",
                "level": 1,
                "description": "User login and JWT token validation.",
                "git_revision": "r",
            },
        )
        handle_theo_upsert_node(
            db_path,
            csv_dir,
            "Concept",
            {
                "id": "ui",
                "name": "UI",
                "level": 1,
                "description": "Frontend HTML rendering.",
                "git_revision": "r",
            },
        )

    def test_returns_matches(self, tmp_theo_project: Path) -> None:
        pytest.importorskip("fastembed")
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        self._seed(db_path, csv_dir)

        result = handle_theo_search(db_path, "how does login work?", None, 5)
        assert result["status"] == "ok"
        assert result["matches"], "expected at least one match"
        # Top result should be the auth concept.
        assert result["matches"][0]["ref"]["id"] == "auth"

    def test_rejects_bad_table(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        result = handle_theo_search(db_path, "x", "Nonsense", 1)
        assert result["status"] == "error"

    def test_reports_missing_fastembed(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        with patch("theo.cli.serve.is_available", return_value=False):
            result = handle_theo_search(db_path, "x", None, 1)
        assert result["status"] == "error"
        assert "fastembed" in result["detail"]


@pytest.mark.integration
class TestAutoIndex:
    def test_upsert_node_populates_embedding(self, tmp_theo_project: Path) -> None:
        pytest.importorskip("fastembed")
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        handle_theo_upsert_node(
            db_path,
            csv_dir,
            "Concept",
            {
                "id": "auto",
                "name": "Auto",
                "description": "auto-indexed via the upsert handler",
                "git_revision": "r",
            },
        )
        rows = run_query(
            db_path, "MATCH (n:Concept {id: 'auto'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is False

    def test_upsert_edge_populates_embedding(self, tmp_theo_project: Path) -> None:
        pytest.importorskip("fastembed")
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        handle_theo_upsert_node(db_path, csv_dir, "Concept", {"id": "a", "git_revision": "r"})
        handle_theo_upsert_node(db_path, csv_dir, "Concept", {"id": "b", "git_revision": "r"})
        handle_theo_upsert_edge(
            db_path,
            csv_dir,
            "PartOf",
            "a",
            "b",
            description="a is part of b",
            git_revision="r",
        )
        rows = run_query(
            db_path,
            "MATCH (:Concept {id:'a'})-[r:PartOf]->(:Concept {id:'b'}) "
            "RETURN r.embedding IS NULL AS is_null",
        )
        assert rows[0]["is_null"] is False

    def test_edge_embedding_failure_does_not_fail_upsert(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        # Seed the endpoint nodes so the upsert_edge call is valid.
        handle_theo_upsert_node(db_path, csv_dir, "Concept", {"id": "a", "git_revision": "r"})
        handle_theo_upsert_node(db_path, csv_dir, "Concept", {"id": "b", "git_revision": "r"})

        def boom(_texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding backend exploded")

        with patch("theo.cli.serve.embed_documents", side_effect=boom):
            result = handle_theo_upsert_edge(
                db_path,
                csv_dir,
                "PartOf",
                "a",
                "b",
                description="important edge",
                git_revision="r",
            )
        assert result["status"] == "ok"
        rows = run_query(
            db_path,
            "MATCH (:Concept {id: 'a'})-[r:PartOf]->(:Concept {id: 'b'}) RETURN count(r) AS c",
        )
        assert rows[0]["c"] == 1

    def test_embedding_failure_does_not_fail_upsert(self, tmp_theo_project: Path) -> None:
        # When embedding raises, the upsert must still return ok and the
        # node must exist in the graph.
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"

        def boom(_texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embedding backend exploded")

        with patch("theo.cli.serve.embed_documents", side_effect=boom):
            result = handle_theo_upsert_node(
                db_path,
                csv_dir,
                "Concept",
                {
                    "id": "robust",
                    "description": "written even though embedding explodes",
                    "git_revision": "r",
                },
            )
        assert result["status"] == "ok"
        rows = run_query(db_path, "MATCH (n:Concept {id: 'robust'}) RETURN n.name")
        assert len(rows) == 1


class TestHandleTheoReload:
    def test_rebuilds_from_csv(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"

        upsert_node(db_path, "Concept", {"id": "persisted", "name": "P"})
        export_csv(db_path, csv_dir)
        # Ephemeral state only in the DB, not in CSVs.
        upsert_node(db_path, "Concept", {"id": "ghost", "name": "G"})

        result = handle_theo_reload(db_path, csv_dir)
        assert result["status"] == "ok"
        assert result["rebuilt"] is True

        rows = run_query(db_path, "MATCH (n:Concept {id: 'ghost'}) RETURN count(n) AS c")
        assert rows[0]["c"] == 0
        rows = run_query(db_path, "MATCH (n:Concept {id: 'persisted'}) RETURN n.name")
        assert rows[0]["n.name"] == "P"

    def test_reports_missing_csvs(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        (csv_dir / "concepts.csv").unlink()
        result = handle_theo_reload(db_path, csv_dir)
        assert result["status"] == "error"
        assert "concepts.csv" in result["detail"]

    @pytest.mark.integration  # type: ignore[misc]
    def test_reindexes_when_fastembed_available(self, tmp_theo_project: Path) -> None:
        pytest.importorskip("fastembed")
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"

        upsert_node(
            db_path,
            "Concept",
            {"id": "with_desc", "name": "WD", "description": "a described thing"},
        )
        export_csv(db_path, csv_dir)

        result = handle_theo_reload(db_path, csv_dir)
        assert result["status"] == "ok"
        assert isinstance(result["reindex"], dict)
        assert result["reindex"]["Concept"] == 1

        rows = run_query(
            db_path, "MATCH (n:Concept {id: 'with_desc'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is False

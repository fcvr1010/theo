"""Integration tests for _db.py (uses real KuzuDB via tmp_db fixture)."""

from __future__ import annotations

from pathlib import Path

from theo._db import (
    export_csv,
    get_stats,
    rebuild_from_csv,
    run_query,
    upsert_edge,
    upsert_node,
)
from theo._schema import CSV_FILES


class TestInitSchema:
    def test_creates_concept_table(self, tmp_db: Path) -> None:
        rows = run_query(tmp_db, "MATCH (n:Concept) RETURN count(n) AS c")
        assert rows[0]["c"] == 0

    def test_creates_source_file_table(self, tmp_db: Path) -> None:
        rows = run_query(tmp_db, "MATCH (n:SourceFile) RETURN count(n) AS c")
        assert rows[0]["c"] == 0

    def test_creates_all_rel_tables(self, tmp_db: Path) -> None:
        # Verify we can query each relationship type without error
        for rel in ["PartOf", "BelongsTo", "InteractsWith", "DependsOn", "Imports"]:
            rows = run_query(tmp_db, f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
            assert rows[0]["c"] == 0


class TestUpsertNode:
    def test_upsert_concept(self, tmp_db: Path) -> None:
        result = upsert_node(
            tmp_db,
            "Concept",
            {
                "id": "auth",
                "name": "Auth System",
                "level": 1,
            },
        )
        assert result["status"] == "ok"
        rows = run_query(tmp_db, "MATCH (n:Concept {id: 'auth'}) RETURN n.name, n.level")
        assert rows[0]["n.name"] == "Auth System"
        assert rows[0]["n.level"] == 1

    def test_upsert_source_file(self, tmp_db: Path) -> None:
        result = upsert_node(
            tmp_db,
            "SourceFile",
            {
                "path": "src/main.py",
                "name": "main.py",
            },
        )
        assert result["status"] == "ok"
        rows = run_query(
            tmp_db,
            "MATCH (n:SourceFile {path: 'src/main.py'}) RETURN n.name",
        )
        assert rows[0]["n.name"] == "main.py"

    def test_upsert_updates_existing(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "c1", "name": "Original"})
        upsert_node(tmp_db, "Concept", {"id": "c1", "name": "Updated"})
        rows = run_query(tmp_db, "MATCH (n:Concept {id: 'c1'}) RETURN n.name")
        assert rows[0]["n.name"] == "Updated"

    def test_rejects_unknown_table(self, tmp_db: Path) -> None:
        result = upsert_node(tmp_db, "Unknown", {"id": "x"})
        assert result["status"] == "error"

    def test_rejects_missing_pk(self, tmp_db: Path) -> None:
        result = upsert_node(tmp_db, "Concept", {"name": "No ID"})
        assert result["status"] == "error"

    def test_rejects_unknown_fields(self, tmp_db: Path) -> None:
        result = upsert_node(tmp_db, "Concept", {"id": "c1", "bogus": "val"})
        assert result["status"] == "error"


class TestUpsertEdge:
    def test_part_of(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "child"})
        upsert_node(tmp_db, "Concept", {"id": "parent"})
        result = upsert_edge(
            tmp_db,
            "PartOf",
            "child",
            "parent",
            "child is part of parent",
            git_revision="abc123",
        )
        assert result["status"] == "ok"

    def test_stores_git_revision(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "a"})
        upsert_node(tmp_db, "Concept", {"id": "b"})
        upsert_edge(tmp_db, "PartOf", "a", "b", "link", git_revision="rev999")
        rows = run_query(
            tmp_db,
            "MATCH (a:Concept)-[r:PartOf]->(b:Concept) RETURN r.git_revision",
        )
        assert rows[0]["r.git_revision"] == "rev999"

    def test_stores_description(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "a"})
        upsert_node(tmp_db, "Concept", {"id": "b"})
        upsert_edge(tmp_db, "PartOf", "a", "b", "my desc", git_revision="abc")
        rows = run_query(
            tmp_db,
            "MATCH ()-[r:PartOf]->() RETURN r.description",
        )
        assert rows[0]["r.description"] == "my desc"

    def test_updates_existing_edge(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "a"})
        upsert_node(tmp_db, "Concept", {"id": "b"})
        upsert_edge(tmp_db, "PartOf", "a", "b", "old desc", git_revision="rev1")
        upsert_edge(tmp_db, "PartOf", "a", "b", "new desc", git_revision="rev2")
        rows = run_query(
            tmp_db,
            "MATCH ()-[r:PartOf]->() RETURN r.description, r.git_revision",
        )
        assert len(rows) == 1
        assert rows[0]["r.description"] == "new desc"
        assert rows[0]["r.git_revision"] == "rev2"

    def test_belongs_to(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "SourceFile", {"path": "src/a.py"})
        upsert_node(tmp_db, "Concept", {"id": "mod"})
        result = upsert_edge(tmp_db, "BelongsTo", "src/a.py", "mod", git_revision="abc123")
        assert result["status"] == "ok"

    def test_imports(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "SourceFile", {"path": "a.py"})
        upsert_node(tmp_db, "SourceFile", {"path": "b.py"})
        result = upsert_edge(tmp_db, "Imports", "a.py", "b.py", git_revision="abc123")
        assert result["status"] == "ok"

    def test_interacts_with(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "x"})
        upsert_node(tmp_db, "Concept", {"id": "y"})
        result = upsert_edge(tmp_db, "InteractsWith", "x", "y", git_revision="abc123")
        assert result["status"] == "ok"

    def test_depends_on(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "a"})
        upsert_node(tmp_db, "Concept", {"id": "b"})
        result = upsert_edge(
            tmp_db,
            "DependsOn",
            "a",
            "b",
            "a depends on b",
            git_revision="abc123",
        )
        assert result["status"] == "ok"

    def test_missing_from_endpoint(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "exists"})
        result = upsert_edge(tmp_db, "PartOf", "nonexistent", "exists", git_revision="abc123")
        assert result["status"] == "error"

    def test_missing_to_endpoint(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "exists"})
        result = upsert_edge(tmp_db, "PartOf", "exists", "nonexistent", git_revision="abc123")
        assert result["status"] == "error"

    def test_unknown_rel_type(self, tmp_db: Path) -> None:
        result = upsert_edge(tmp_db, "Bogus", "a", "b", git_revision="abc123")
        assert result["status"] == "error"


class TestExportAndRebuild:
    def test_export_csv_produces_node_files(self, tmp_db: Path, tmp_path: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "c1", "name": "One"})
        csv_dir = tmp_path / "csv"
        export_csv(tmp_db, csv_dir)
        assert (csv_dir / CSV_FILES["Concept"]).exists()
        content = (csv_dir / CSV_FILES["Concept"]).read_text()
        assert "c1" in content

    def test_export_csv_produces_edge_files(self, tmp_db: Path, tmp_path: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "a"})
        upsert_node(tmp_db, "Concept", {"id": "b"})
        upsert_edge(tmp_db, "PartOf", "a", "b", "link", git_revision="rev1")
        csv_dir = tmp_path / "csv"
        export_csv(tmp_db, csv_dir)
        assert (csv_dir / CSV_FILES["PartOf"]).exists()
        content = (csv_dir / CSV_FILES["PartOf"]).read_text()
        assert "link" in content
        assert "rev1" in content

    def test_round_trip_rebuild(self, tmp_db: Path, tmp_path: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "c1", "name": "Alpha", "git_revision": "abc123"})
        upsert_node(tmp_db, "Concept", {"id": "c2", "name": "Beta"})
        upsert_node(
            tmp_db, "SourceFile", {"path": "f.py", "name": "f.py", "git_revision": "abc123"}
        )
        upsert_edge(tmp_db, "PartOf", "c1", "c2", "part of", git_revision="abc123")
        upsert_edge(tmp_db, "BelongsTo", "f.py", "c1", git_revision="abc123")

        csv_dir = tmp_path / "csv"
        export_csv(tmp_db, csv_dir)

        # Rebuild into a new DB
        db2 = tmp_path / "rebuilt.db"
        rebuild_from_csv(db2, csv_dir)

        rows = run_query(db2, "MATCH (n:Concept) RETURN n.id, n.git_revision ORDER BY n.id")
        assert [r["n.id"] for r in rows] == ["c1", "c2"]
        assert rows[0]["n.git_revision"] == "abc123"

        rows = run_query(db2, "MATCH (n:SourceFile) RETURN n.path")
        assert rows[0]["n.path"] == "f.py"

        rows = run_query(
            db2,
            "MATCH (a:Concept)-[r:PartOf]->(b:Concept) "
            "RETURN a.id, b.id, r.description, r.git_revision",
        )
        assert len(rows) == 1
        assert rows[0]["a.id"] == "c1"
        assert rows[0]["b.id"] == "c2"
        assert rows[0]["r.git_revision"] == "abc123"

        rows = run_query(
            db2,
            "MATCH (f:SourceFile)-[r:BelongsTo]->(c:Concept) RETURN f.path, c.id, r.git_revision",
        )
        assert len(rows) == 1
        assert rows[0]["r.git_revision"] == "abc123"


class TestGetStats:
    def test_returns_correct_counts(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "a"})
        upsert_node(tmp_db, "Concept", {"id": "b"})
        upsert_node(tmp_db, "SourceFile", {"path": "x.py"})
        upsert_edge(tmp_db, "PartOf", "a", "b", git_revision="abc123")

        stats = get_stats(tmp_db)
        assert stats["node_counts"]["Concept"] == 2
        assert stats["node_counts"]["SourceFile"] == 1
        assert stats["edge_counts"]["PartOf"] == 1
        assert stats["edge_counts"]["Imports"] == 0


class TestRunQuery:
    def test_returns_results(self, tmp_db: Path) -> None:
        upsert_node(tmp_db, "Concept", {"id": "q1", "name": "Query Test"})
        rows = run_query(tmp_db, "MATCH (n:Concept) RETURN n.id, n.name")
        assert len(rows) == 1
        assert rows[0]["n.id"] == "q1"
        assert rows[0]["n.name"] == "Query Test"

    def test_empty_result(self, tmp_db: Path) -> None:
        rows = run_query(tmp_db, "MATCH (n:Concept) RETURN n.id")
        assert rows == []

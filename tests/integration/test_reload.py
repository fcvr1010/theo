"""Integration tests for ``theo reload``."""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from theo._db import export_csv, run_query, upsert_edge, upsert_node
from theo.cli.reload import run


class TestReload:
    def test_rebuilds_db_from_csvs(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"

        # Seed the DB, export CSVs, then mutate the DB out of band.
        upsert_node(db_path, "Concept", {"id": "root", "name": "Root"})
        upsert_node(db_path, "Concept", {"id": "child", "name": "Child"})
        upsert_edge(db_path, "PartOf", "child", "root", git_revision="r1")
        export_csv(db_path, csv_dir)

        # Introduce state that only exists in the DB, not in the CSVs.
        upsert_node(db_path, "Concept", {"id": "ephemeral", "name": "Ghost"})
        assert (
            run_query(db_path, "MATCH (n:Concept {id: 'ephemeral'}) RETURN count(n) AS c")[0]["c"]
            == 1
        )

        run(str(tmp_theo_project))

        # Ghost is gone; CSV-backed rows survive.
        rows = run_query(db_path, "MATCH (n:Concept {id: 'ephemeral'}) RETURN count(n) AS c")
        assert rows[0]["c"] == 0
        rows = run_query(db_path, "MATCH (n:Concept {id: 'root'}) RETURN n.name")
        assert rows[0]["n.name"] == "Root"
        rows = run_query(
            db_path,
            "MATCH (:Concept {id: 'child'})-[r:PartOf]->(:Concept {id: 'root'}) "
            "RETURN count(r) AS c",
        )
        assert rows[0]["c"] == 1

    def test_rebuilds_when_db_missing(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"
        upsert_node(db_path, "Concept", {"id": "solo", "name": "Solo"})
        export_csv(db_path, csv_dir)
        db_path.unlink()

        run(str(tmp_theo_project))

        assert db_path.exists()
        rows = run_query(db_path, "MATCH (n:Concept {id: 'solo'}) RETURN n.name")
        assert rows[0]["n.name"] == "Solo"

    def test_exits_when_no_theo_root(self, tmp_path: Path) -> None:
        with pytest.raises(click.exceptions.Exit):
            run(str(tmp_path))

    def test_exits_when_csvs_missing(self, tmp_theo_project: Path) -> None:
        (tmp_theo_project / ".theo" / "concepts.csv").unlink()
        with pytest.raises(click.exceptions.Exit):
            run(str(tmp_theo_project))

    @pytest.mark.integration  # type: ignore[misc]
    def test_reload_rebuilds_embeddings(self, tmp_theo_project: Path) -> None:
        pytest.importorskip("fastembed")
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        csv_dir = tmp_theo_project / ".theo"

        upsert_node(
            db_path,
            "Concept",
            {
                "id": "described",
                "name": "D",
                "description": "a described thing",
                "git_revision": "r",
            },
        )
        export_csv(db_path, csv_dir)
        db_path.unlink()

        run(str(tmp_theo_project))

        rows = run_query(
            db_path, "MATCH (n:Concept {id: 'described'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is False

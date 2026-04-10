"""Integration tests for COW lifecycle with real KuzuDB."""

from __future__ import annotations

import glob as glob_mod
from pathlib import Path

from theo._cow import abort_write, begin_write, commit_write
from theo._db import run_query, upsert_node


class TestCowLifecycle:
    def test_full_cow_cycle(self, tmp_db: Path, tmp_path: Path) -> None:
        """Init DB, begin_write, upsert to tmp, commit, verify in original."""
        upsert_node(tmp_db, "Concept", {"id": "before", "name": "Before"})

        tmp_copy = begin_write(tmp_db)
        upsert_node(tmp_copy, "Concept", {"id": "during", "name": "During COW"})
        commit_write(tmp_copy, tmp_db)

        rows = run_query(tmp_db, "MATCH (n:Concept) RETURN n.id ORDER BY n.id")
        ids = [r["n.id"] for r in rows]
        assert "before" in ids
        assert "during" in ids

    def test_no_tmp_files_after_commit(self, tmp_db: Path) -> None:
        tmp_copy = begin_write(tmp_db)
        upsert_node(tmp_copy, "Concept", {"id": "test"})
        commit_write(tmp_copy, tmp_db)

        # No .tmp. files should remain
        tmp_files = glob_mod.glob(str(tmp_db.parent / "*.tmp.*"))
        assert len(tmp_files) == 0

    def test_abort_cleans_up(self, tmp_db: Path) -> None:
        tmp_copy = begin_write(tmp_db)
        upsert_node(tmp_copy, "Concept", {"id": "aborted"})
        abort_write(tmp_copy)

        assert not tmp_copy.exists()
        # Original DB should not have the aborted write
        rows = run_query(tmp_db, "MATCH (n:Concept {id: 'aborted'}) RETURN n.id")
        assert len(rows) == 0

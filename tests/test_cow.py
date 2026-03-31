"""Tests for theo.graph.begin_write and theo.graph.commit_write (COW sessions)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from theo.graph.begin_write import STALE_THRESHOLD_SECONDS, begin_write
from theo.graph.commit_write import commit_write
from theo.graph.init_db import init_db
from theo.graph.upsert_node import upsert_node


class TestBeginWrite:
    """Test COW session creation."""

    def test_returns_cow_path(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        cow_path = begin_write(db_path)
        assert ".cow_" in cow_path
        assert Path(cow_path).exists()

    def test_cow_path_is_different_from_main(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        cow_path = begin_write(db_path)
        assert cow_path != db_path

    def test_cow_is_a_copy_of_main(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        upsert_node(db_path, "Concept", {"id": "pre", "name": "Pre-COW"})

        cow_path = begin_write(db_path)

        # The COW copy should contain the pre-existing data.
        import real_ladybug as lb

        db = lb.Database(cow_path, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute("MATCH (c:Concept {id: 'pre'}) RETURN c.name")
        assert r.has_next()
        assert r.get_next()[0] == "Pre-COW"

    def test_cow_when_main_does_not_exist(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "nonexistent.db")
        cow_path = begin_write(db_path)
        # COW file should not exist (no source to copy), but the directory should.
        assert not Path(cow_path).exists()
        assert Path(cow_path).parent.exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "deep" / "nested" / "test.db")
        cow_path = begin_write(db_path)
        assert Path(cow_path).parent.exists()

    def test_cleans_up_stale_cow_files(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Create a fake stale COW file.
        stale = tmp_path / "test.db.cow_stale12345"
        stale.write_text("stale")
        # Set its mtime to be older than the threshold.
        old_time = time.time() - STALE_THRESHOLD_SECONDS - 100
        import os

        os.utime(str(stale), (old_time, old_time))

        begin_write(db_path)
        assert not stale.exists()

    def test_does_not_clean_fresh_cow_files(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Create a recent COW file.
        recent = tmp_path / "test.db.cow_recent12345"
        recent.write_text("recent")

        begin_write(db_path)
        # The recent COW file should still exist.
        assert recent.exists()

    def test_multiple_cow_sessions(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        cow1 = begin_write(db_path)
        cow2 = begin_write(db_path)
        assert cow1 != cow2
        assert Path(cow1).exists()
        assert Path(cow2).exists()


class TestCommitWrite:
    """Test COW session commit (atomic replace)."""

    def test_commit_replaces_main(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        cow_path = begin_write(db_path)
        # Write something to the COW copy.
        upsert_node(cow_path, "Concept", {"id": "new", "name": "New"})

        result = commit_write(cow_path, db_path)
        assert result["status"] == "ok"

        # The COW file should no longer exist.
        assert not Path(cow_path).exists()

        # The main DB should have the new data.
        import real_ladybug as lb

        db = lb.Database(db_path, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute("MATCH (c:Concept {id: 'new'}) RETURN c.name")
        assert r.has_next()
        assert r.get_next()[0] == "New"

    def test_commit_nonexistent_cow_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            commit_write(str(tmp_path / "nonexistent.cow"), str(tmp_path / "test.db"))

    def test_full_cow_workflow(self, tmp_path: Path) -> None:
        """End-to-end: init -> insert -> begin_write -> modify COW -> commit."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        upsert_node(db_path, "Concept", {"id": "original", "name": "Original"})

        # Begin COW session.
        cow_path = begin_write(db_path)

        # Modify the COW copy.
        upsert_node(cow_path, "Concept", {"id": "added-in-cow", "name": "COW Node"})
        upsert_node(cow_path, "Concept", {"id": "original", "name": "Modified"})

        # Commit.
        commit_write(cow_path, db_path)

        # Verify.
        import real_ladybug as lb

        db = lb.Database(db_path, read_only=True)
        conn = lb.Connection(db)

        r = conn.execute("MATCH (c:Concept {id: 'added-in-cow'}) RETURN c.name")
        assert r.has_next()
        assert r.get_next()[0] == "COW Node"

        r = conn.execute("MATCH (c:Concept {id: 'original'}) RETURN c.name")
        assert r.has_next()
        assert r.get_next()[0] == "Modified"

    def test_concurrent_read_during_cow(self, tmp_path: Path) -> None:
        """Main DB remains readable while a COW session is active."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        upsert_node(db_path, "Concept", {"id": "stable", "name": "Stable"})

        cow_path = begin_write(db_path)

        # Write to COW.
        upsert_node(cow_path, "Concept", {"id": "cow-only", "name": "COW Only"})

        # Read from main -- should NOT see cow-only.
        import real_ladybug as lb

        db = lb.Database(db_path, read_only=True)
        conn = lb.Connection(db)
        r = conn.execute("MATCH (c:Concept) RETURN c.id ORDER BY c.id")
        ids = []
        while r.has_next():
            ids.append(r.get_next()[0])
        assert "stable" in ids
        assert "cow-only" not in ids

        # Clean up: commit the COW.
        del conn
        db.close()
        commit_write(cow_path, db_path)

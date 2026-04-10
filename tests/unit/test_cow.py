"""Unit tests for _cow.py (mocked filesystem)."""

from __future__ import annotations

from pathlib import Path

from theo._cow import abort_write, begin_write, commit_write


class TestBeginWrite:
    def test_copies_main_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"database content")
        tmp = begin_write(db_path)
        assert tmp.exists()
        assert tmp.read_bytes() == b"database content"
        assert tmp != db_path

    def test_copies_wal_sidecar(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"db")
        wal = Path(str(db_path) + ".wal")
        wal.write_bytes(b"wal content")
        tmp = begin_write(db_path)
        tmp_wal = Path(str(tmp) + ".wal")
        assert tmp_wal.exists()
        assert tmp_wal.read_bytes() == b"wal content"

    def test_works_without_wal(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"db")
        tmp = begin_write(db_path)
        tmp_wal = Path(str(tmp) + ".wal")
        assert not tmp_wal.exists()
        assert tmp.exists()


class TestCommitWrite:
    def test_renames_both_files(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"original")
        tmp = begin_write(db_path)
        tmp.write_bytes(b"modified")
        commit_write(tmp, db_path)
        assert db_path.read_bytes() == b"modified"
        assert not tmp.exists()

    def test_renames_wal(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"db")
        wal = Path(str(db_path) + ".wal")
        wal.write_bytes(b"wal")
        tmp = begin_write(db_path)
        commit_write(tmp, db_path)
        assert db_path.exists()

    def test_removes_stale_wal(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"original")
        db_wal = Path(str(db_path) + ".wal")
        db_wal.write_bytes(b"stale wal")

        # Create tmp without a WAL
        tmp = tmp_path / "test.db.tmp.abc123"
        tmp.write_bytes(b"modified")

        commit_write(tmp, db_path)
        assert not db_wal.exists()


class TestAbortWrite:
    def test_removes_tmp_files(self, tmp_path: Path) -> None:
        tmp = tmp_path / "test.db.tmp.abc123"
        tmp.write_bytes(b"data")
        tmp_wal = Path(str(tmp) + ".wal")
        tmp_wal.write_bytes(b"wal")
        abort_write(tmp)
        assert not tmp.exists()
        assert not tmp_wal.exists()

    def test_tolerates_missing_files(self, tmp_path: Path) -> None:
        tmp = tmp_path / "nonexistent.db.tmp.abc123"
        abort_write(tmp)  # Should not raise

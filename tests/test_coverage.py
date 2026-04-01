"""Tests for theo.tools.get_coverage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from theo.tools.get_coverage import get_coverage
from theo.tools.init_db import init_db
from theo.tools.upsert_node import upsert_node


class TestGetCoverage:
    """Test coverage analysis."""

    def test_empty_db_empty_repo(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        repo = tmp_path / "repo"
        repo.mkdir()
        init_db(db_path)

        result = get_coverage(db_path, str(repo))
        assert result["total"] == 0
        assert result["indexed"] == 0
        assert result["coverage_pct"] == 100.0
        assert result["unindexed"] == []

    def test_files_on_disk_none_indexed(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "src"
        src.mkdir(parents=True)
        (src / "main.py").write_text("# main")
        (src / "utils.py").write_text("# utils")

        result = get_coverage(
            db_path,
            str(repo),
            source_dirs=["src"],
            extensions={".py"},
        )
        assert result["total"] == 2
        assert result["indexed"] == 0
        assert result["coverage_pct"] == 0.0
        assert len(result["unindexed"]) == 2

    def test_partial_coverage(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "lib"
        src.mkdir(parents=True)
        (src / "a.py").write_text("# a")
        (src / "b.py").write_text("# b")

        # Index one of the two files.
        upsert_node(db_path, "SourceFile", {"path": "lib/a.py", "name": "a.py"})

        result = get_coverage(
            db_path,
            str(repo),
            source_dirs=["lib"],
            extensions={".py"},
        )
        assert result["total"] == 2
        assert result["indexed"] == 1
        assert result["coverage_pct"] == 50.0
        assert result["unindexed"] == ["lib/b.py"]

    def test_full_coverage(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "pkg"
        src.mkdir(parents=True)
        (src / "mod.py").write_text("# mod")

        upsert_node(db_path, "SourceFile", {"path": "pkg/mod.py", "name": "mod.py"})

        result = get_coverage(
            db_path,
            str(repo),
            source_dirs=["pkg"],
            extensions={".py"},
        )
        assert result["total"] == 1
        assert result["indexed"] == 1
        assert result["coverage_pct"] == 100.0
        assert result["unindexed"] == []

    def test_custom_extensions(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "code"
        src.mkdir(parents=True)
        (src / "app.ts").write_text("// app")
        (src / "app.py").write_text("# app")
        (src / "app.rs").write_text("// app")

        result = get_coverage(
            db_path,
            str(repo),
            source_dirs=["code"],
            extensions={".ts", ".rs"},
        )
        assert result["total"] == 2  # .ts and .rs only
        assert "code/app.py" not in result["unindexed"]

    def test_skips_pycache(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "pkg"
        cache = src / "__pycache__"
        cache.mkdir(parents=True)
        (src / "real.py").write_text("# real")
        (cache / "cached.py").write_text("# cached")

        result = get_coverage(
            db_path,
            str(repo),
            source_dirs=["pkg"],
            extensions={".py"},
        )
        assert result["total"] == 1
        paths = result["unindexed"]
        assert all("__pycache__" not in p for p in paths)

    def test_default_extensions_include_common_languages(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "code"
        src.mkdir(parents=True)
        for ext in [".py", ".js", ".ts", ".rs", ".go", ".java", ".md"]:
            (src / f"file{ext}").write_text(f"# {ext}")
        # Also a .txt that should be excluded.
        (src / "notes.txt").write_text("notes")

        result = get_coverage(db_path, str(repo), source_dirs=["code"])
        assert result["total"] == 7  # All 7 default extensions, not .txt

    def test_nonexistent_source_dir_ignored(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        repo.mkdir()

        result = get_coverage(
            db_path,
            str(repo),
            source_dirs=["nonexistent"],
            extensions={".py"},
        )
        assert result["total"] == 0

    def test_stale_key_present_in_result(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        repo = tmp_path / "repo"
        repo.mkdir()
        init_db(db_path)

        result = get_coverage(db_path, str(repo))
        assert "stale" in result
        assert result["stale"] == []

    def test_stale_files_detected(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "lib"
        src.mkdir(parents=True)
        (src / "a.py").write_text("# a")
        (src / "b.py").write_text("# b")

        # Index both files with an old revision.
        upsert_node(
            db_path,
            "SourceFile",
            {"path": "lib/a.py", "name": "a.py", "git_revision": "old_rev"},
        )
        upsert_node(
            db_path,
            "SourceFile",
            {"path": "lib/b.py", "name": "b.py", "git_revision": "current_head"},
        )

        with patch("theo.tools.get_coverage._get_git_head", return_value="current_head"):
            result = get_coverage(
                db_path,
                str(repo),
                source_dirs=["lib"],
                extensions={".py"},
            )

        assert result["stale"] == ["lib/a.py"]
        assert result["indexed"] == 2
        assert result["unindexed"] == []

    def test_stale_empty_when_no_git(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "pkg"
        src.mkdir(parents=True)
        (src / "mod.py").write_text("# mod")

        upsert_node(
            db_path,
            "SourceFile",
            {"path": "pkg/mod.py", "name": "mod.py", "git_revision": "old"},
        )

        with patch("theo.tools.get_coverage._get_git_head", return_value=None):
            result = get_coverage(
                db_path,
                str(repo),
                source_dirs=["pkg"],
                extensions={".py"},
            )

        assert result["stale"] == []

    def test_stale_ignores_null_revision(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        repo = tmp_path / "repo"
        src = repo / "pkg"
        src.mkdir(parents=True)
        (src / "mod.py").write_text("# mod")

        # Index without git_revision (None).
        upsert_node(db_path, "SourceFile", {"path": "pkg/mod.py", "name": "mod.py"})

        with patch("theo.tools.get_coverage._get_git_head", return_value="abc123"):
            result = get_coverage(
                db_path,
                str(repo),
                source_dirs=["pkg"],
                extensions={".py"},
            )

        # Null revision should not be considered stale.
        assert result["stale"] == []

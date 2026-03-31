"""Tests for theo.client.get_coverage."""

from __future__ import annotations

from pathlib import Path

from theo.client.get_coverage import get_coverage
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

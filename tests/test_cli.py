"""Tests for theo.cli."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from theo import __version__
from theo.cli import main


class TestVersion:
    """theo --version prints the version string."""

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit, match="0"), patch("sys.argv", ["theo", "--version"]):
            main()
        captured = capsys.readouterr()
        assert f"theo {__version__}" in captured.out


class TestInit:
    """theo init creates .theo/, DB, and state.json."""

    def test_init_creates_theo_dir(self, tmp_path: Path) -> None:
        with patch("sys.argv", ["theo", "init", str(tmp_path)]):
            rc = main()
        assert rc == 0
        assert (tmp_path / ".theo").is_dir()
        assert (tmp_path / ".theo" / "logs").is_dir()
        # DB directory is created by init_db
        assert Path(tmp_path / ".theo" / "db").exists()

    def test_init_creates_state_json(self, tmp_path: Path) -> None:
        with patch("sys.argv", ["theo", "init", str(tmp_path)]):
            main()
        state_file = tmp_path / ".theo" / "state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["project"] == tmp_path.name
        assert data["last_indexed_commit"] is None
        assert data["last_indexed_at"] is None

    def test_init_prints_success(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["theo", "init", str(tmp_path)]):
            main()
        out = capsys.readouterr().out
        assert f"Theo initialised in {tmp_path}" in out
        assert "Graph DB:" in out

    def test_init_idempotent(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["theo", "init", str(tmp_path)]):
            main()
        with patch("sys.argv", ["theo", "init", str(tmp_path)]):
            rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "already initialised" in out

    def test_init_defaults_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["theo", "init"]):
            rc = main()
        assert rc == 0
        assert (tmp_path / ".theo").is_dir()

    def test_init_nonexistent_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("sys.argv", ["theo", "init", "/nonexistent/path"]):
            rc = main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "does not exist" in err

    def test_init_file_path(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        a_file = tmp_path / "somefile.txt"
        a_file.write_text("hello")
        with patch("sys.argv", ["theo", "init", str(a_file)]):
            rc = main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "not a directory" in err


class TestStats:
    """theo stats shows project information."""

    def test_stats_before_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["theo", "stats"]):
            rc = main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "not initialised" in err

    def test_stats_after_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # First init
        with patch("sys.argv", ["theo", "init", str(tmp_path)]):
            main()

        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["theo", "stats"]):
            rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert f"Project:          {tmp_path.name}" in out
        assert "Last indexed:     never" in out
        assert "Nodes:" in out
        assert "Coverage:" in out

    def test_stats_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("sys.argv", ["theo", "init", str(tmp_path)]):
            main()
        capsys.readouterr()  # discard init output

        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["theo", "stats", "--json"]):
            rc = main()
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["project"] == tmp_path.name
        assert "last_indexed_commit" in data
        assert "last_indexed_at" in data
        assert "node_counts" in data
        assert isinstance(data["coverage_pct"], int | float)

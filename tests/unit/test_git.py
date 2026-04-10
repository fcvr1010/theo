"""Unit tests for _git.py (mocked subprocess)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from theo._git import find_theo_root, head_commit


class TestHeadCommit:
    @patch("theo._git.subprocess.run")
    def test_returns_stripped_hash(self, mock_run: MagicMock) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "abc123def456\n"
        result = head_commit()
        assert result == "abc123def456"

    @patch("theo._git.subprocess.run")
    def test_returns_none_when_not_git_repo(self, mock_run: MagicMock) -> None:
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        result = head_commit()
        assert result is None


class TestFindTheoRoot:
    def test_finds_theo_root_in_current_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".theo").mkdir()
        (tmp_path / ".theo" / "config.json").write_text("{}")
        result = find_theo_root(tmp_path)
        assert result == tmp_path

    def test_finds_theo_root_in_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".theo").mkdir()
        (tmp_path / ".theo" / "config.json").write_text("{}")
        child = tmp_path / "sub" / "dir"
        child.mkdir(parents=True)
        result = find_theo_root(child)
        assert result == tmp_path

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        child = tmp_path / "sub" / "dir"
        child.mkdir(parents=True)
        result = find_theo_root(child)
        assert result is None

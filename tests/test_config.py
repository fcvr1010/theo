"""Tests for theo.config."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from theo.config import TheoConfig


class TestTheoConfig:
    """Test configuration defaults and env var overrides."""

    def test_default_project_dir(self) -> None:
        config = TheoConfig()
        assert config.project_dir == Path.cwd()

    def test_explicit_project_dir(self, tmp_path: Path) -> None:
        config = TheoConfig(project_dir=tmp_path / "my-project")
        assert config.project_dir == tmp_path / "my-project"

    def test_theo_dir(self, tmp_path: Path) -> None:
        config = TheoConfig(project_dir=tmp_path)
        assert config.theo_dir == tmp_path / ".theo"

    def test_db_path(self, tmp_path: Path) -> None:
        config = TheoConfig(project_dir=tmp_path)
        assert config.db_path == str(tmp_path / ".theo" / "db")

    def test_state_file(self, tmp_path: Path) -> None:
        config = TheoConfig(project_dir=tmp_path)
        assert config.state_file == tmp_path / ".theo" / "state.json"

    def test_ensure_dirs_creates_theo_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "new_project"
        project.mkdir()
        config = TheoConfig(project_dir=project)
        config.ensure_dirs()
        assert config.theo_dir.exists()
        assert (config.theo_dir / "logs").exists()

    def test_ensure_dirs_idempotent(self, tmp_path: Path) -> None:
        config = TheoConfig(project_dir=tmp_path)
        config.ensure_dirs()
        config.ensure_dirs()  # Should not raise.
        assert config.theo_dir.exists()

    def test_default_embedding_model(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("THEO_EMBEDDING_MODEL", None)
            config = TheoConfig()
            assert config.embedding_model == "nomic-ai/nomic-embed-text-v1.5"

    def test_embedding_model_from_env(self) -> None:
        with patch.dict(os.environ, {"THEO_EMBEDDING_MODEL": "custom/model"}):
            config = TheoConfig()
            assert config.embedding_model == "custom/model"

    def test_default_embedding_dim(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("THEO_EMBEDDING_DIM", None)
            config = TheoConfig()
            assert config.embedding_dim == 768

    def test_embedding_dim_from_env(self) -> None:
        with patch.dict(os.environ, {"THEO_EMBEDDING_DIM": "384"}):
            config = TheoConfig()
            assert config.embedding_dim == 384


class TestResolveDbPath:
    """Test backward-compatible resolve_db_path helper."""

    def test_resolve_db_path(self, tmp_path: Path) -> None:
        from theo.config import resolve_db_path

        with patch.dict(os.environ, {"THEO_BASE_DIR": str(tmp_path)}):
            result = resolve_db_path("test-repo")
            assert result == str(tmp_path / "db" / "test-repo")

    def test_resolve_db_path_rejects_slashes(self) -> None:
        import pytest

        from theo.config import resolve_db_path

        with pytest.raises(ValueError, match="path separators"):
            resolve_db_path("foo/bar")
        with pytest.raises(ValueError, match="path separators"):
            resolve_db_path("foo\\bar")

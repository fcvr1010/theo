"""Tests for theo.config."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from theo.config import TheoConfig


class TestTheoConfig:
    """Test configuration defaults and env var overrides."""

    def test_default_base_dir(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # Remove THEO_BASE_DIR if present.
            os.environ.pop("THEO_BASE_DIR", None)
            config = TheoConfig()
            assert config.base_dir == Path.home() / ".theo"

    def test_base_dir_from_env(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"THEO_BASE_DIR": str(tmp_path / "custom")}):
            config = TheoConfig()
            assert config.base_dir == tmp_path / "custom"

    def test_default_frequency(self) -> None:
        config = TheoConfig()
        assert config.default_frequency_minutes == 30

    def test_default_cli_command(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("THEO_CLI_COMMAND", None)
            config = TheoConfig()
            assert config.cli_command == "claude"

    def test_cli_command_from_env(self) -> None:
        with patch.dict(os.environ, {"THEO_CLI_COMMAND": "custom-cli"}):
            config = TheoConfig()
            assert config.cli_command == "custom-cli"

    def test_ensure_dirs_creates_base(self, tmp_path: Path) -> None:
        base = tmp_path / "new_base"
        config = TheoConfig(base_dir=base)
        config.ensure_dirs()
        assert base.exists()
        assert (base / "logs").exists()
        assert (base / "db").exists()

    def test_ensure_dirs_idempotent(self, tmp_path: Path) -> None:
        base = tmp_path / "idempotent"
        config = TheoConfig(base_dir=base)
        config.ensure_dirs()
        config.ensure_dirs()  # Should not raise.
        assert base.exists()

    def test_custom_frequency(self) -> None:
        config = TheoConfig(default_frequency_minutes=60)
        assert config.default_frequency_minutes == 60

    def test_explicit_base_dir_overrides_env(self, tmp_path: Path) -> None:
        explicit = tmp_path / "explicit"
        with patch.dict(os.environ, {"THEO_BASE_DIR": str(tmp_path / "env")}):
            config = TheoConfig(base_dir=explicit)
            assert config.base_dir == explicit

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

    def test_db_path_for_repo(self, tmp_path: Path) -> None:
        config = TheoConfig(base_dir=tmp_path)
        assert config.db_path_for_repo("my-repo") == str(tmp_path / "db" / "my-repo")

    def test_db_path_for_repo_rejects_slashes(self, tmp_path: Path) -> None:
        import pytest

        config = TheoConfig(base_dir=tmp_path)
        with pytest.raises(ValueError, match="path separators"):
            config.db_path_for_repo("foo/bar")
        with pytest.raises(ValueError, match="path separators"):
            config.db_path_for_repo("foo\\bar")

    def test_resolve_db_path(self, tmp_path: Path) -> None:
        from theo.config import resolve_db_path

        with patch.dict(os.environ, {"THEO_BASE_DIR": str(tmp_path)}):
            result = resolve_db_path("test-repo")
            assert result == str(tmp_path / "db" / "test-repo")

"""Tests for theo.config."""

from __future__ import annotations

import os
from unittest.mock import patch

from theo.config import TheoConfig


class TestTheoConfig:
    """Test configuration defaults and env var overrides."""

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

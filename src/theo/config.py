"""Theo configuration.

    TheoConfig(embedding_model, embedding_dim)

Supports env var overrides: ``THEO_EMBEDDING_MODEL``, ``THEO_EMBEDDING_DIM``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _default_embedding_model() -> str:
    return os.environ.get("THEO_EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")


def _default_embedding_dim() -> int:
    return int(os.environ.get("THEO_EMBEDDING_DIM", "768"))


@dataclass
class TheoConfig:
    """Runtime configuration for Theo."""

    embedding_model: str = field(default_factory=_default_embedding_model)
    embedding_dim: int = field(default_factory=_default_embedding_dim)

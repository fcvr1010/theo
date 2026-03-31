"""Theo configuration.

    TheoConfig(base_dir, default_frequency_minutes, cli_command, embedding_model, embedding_dim)

Supports env var overrides: ``THEO_BASE_DIR``, ``THEO_CLI_COMMAND``,
``THEO_EMBEDDING_MODEL``, ``THEO_EMBEDDING_DIM``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_base_dir() -> Path:
    env = os.environ.get("THEO_BASE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".theo"


def _default_cli_command() -> str:
    return os.environ.get("THEO_CLI_COMMAND", "claude")


def _default_embedding_model() -> str:
    return os.environ.get("THEO_EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")


def _default_embedding_dim() -> int:
    return int(os.environ.get("THEO_EMBEDDING_DIM", "768"))


@dataclass
class TheoConfig:
    """Runtime configuration for Theo."""

    base_dir: Path = field(default_factory=_default_base_dir)
    default_frequency_minutes: int = 30
    cli_command: str = field(default_factory=_default_cli_command)
    embedding_model: str = field(default_factory=_default_embedding_model)
    embedding_dim: int = field(default_factory=_default_embedding_dim)

    def ensure_dirs(self) -> None:
        """Create the base directory and standard subdirectories if they do not exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "db").mkdir(parents=True, exist_ok=True)

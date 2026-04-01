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

    def db_path_for_repo(self, repo: str) -> str:
        """Return the database path for a given repository name.

        Convention: ``{base_dir}/db/{repo}``.  The *repo* argument is a
        short identifier (e.g. ``"vito"``, ``"theo"``) -- it must not
        contain path separators.
        """
        if "/" in repo or "\\" in repo:
            raise ValueError(f"repo must be a simple name without path separators, got: {repo!r}")
        return str(self.base_dir / "db" / repo)

    def ensure_dirs(self) -> None:
        """Create the base directory and standard subdirectories if they do not exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "db").mkdir(parents=True, exist_ok=True)


def resolve_db_path(repo: str) -> str:
    """Convenience: resolve a repo name to its database path using default config."""
    return TheoConfig().db_path_for_repo(repo)

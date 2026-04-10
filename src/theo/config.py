"""Theo configuration.

    TheoConfig(project_dir, embedding_model, embedding_dim)

Supports env var overrides: ``THEO_EMBEDDING_MODEL``, ``THEO_EMBEDDING_DIM``.

Theo is project-local: the graph lives at ``<project_dir>/.theo/db``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_embedding_model() -> str:
    return os.environ.get("THEO_EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")


def _default_embedding_dim() -> int:
    return int(os.environ.get("THEO_EMBEDDING_DIM", "768"))


@dataclass
class TheoConfig:
    """Runtime configuration for Theo (project-local)."""

    project_dir: Path = field(default_factory=Path.cwd)
    embedding_model: str = field(default_factory=_default_embedding_model)
    embedding_dim: int = field(default_factory=_default_embedding_dim)

    @property
    def theo_dir(self) -> Path:
        """Return the ``.theo`` directory inside the project."""
        return self.project_dir / ".theo"

    @property
    def db_path(self) -> str:
        """Return the database path for this project."""
        return str(self.theo_dir / "db")

    @property
    def state_file(self) -> Path:
        """Return the path to the project state file."""
        return self.theo_dir / "state.json"

    def ensure_dirs(self) -> None:
        """Create the ``.theo`` directory and standard subdirectories."""
        self.theo_dir.mkdir(parents=True, exist_ok=True)
        (self.theo_dir / "logs").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Backward-compatible helpers used by client modules (query.py,
# semantic_search.py).  These still resolve via THEO_BASE_DIR for the
# multi-repo client path.  They will be migrated to project-local config
# in a future ticket.
# ---------------------------------------------------------------------------


def _default_base_dir() -> Path:
    env = os.environ.get("THEO_BASE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".theo"


def resolve_db_path(repo: str) -> str:
    """Resolve a repo name to its database path using THEO_BASE_DIR.

    Convention: ``{base_dir}/db/{repo}``.

    .. deprecated::
        Use ``TheoConfig.db_path`` for project-local access instead.
    """
    base = _default_base_dir()
    if "/" in repo or "\\" in repo:
        raise ValueError(f"repo must be a simple name without path separators, got: {repo!r}")
    return str(base / "db" / repo)

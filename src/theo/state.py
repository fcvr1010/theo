"""Theo project state — tracks indexing progress in ``.theo/state.json``.

    load_state(config) -> TheoState
    save_state(config, state) -> None
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from theo.config import TheoConfig


@dataclass
class TheoState:
    """Serialisable state for a Theo project."""

    project: str
    last_indexed_commit: str | None = None
    last_indexed_at: str | None = None  # ISO 8601


def load_state(config: TheoConfig) -> TheoState:
    """Load project state from ``.theo/state.json``.

    Raises ``FileNotFoundError`` if the state file does not exist.
    """
    data = json.loads(config.state_file.read_text(encoding="utf-8"))
    return TheoState(
        project=data["project"],
        last_indexed_commit=data.get("last_indexed_commit"),
        last_indexed_at=data.get("last_indexed_at"),
    )


def save_state(config: TheoConfig, state: TheoState) -> None:
    """Persist project state atomically (write to tmp file then rename)."""
    config.theo_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), indent=2) + "\n"

    # Atomic write: write to a temp file in the same directory, then rename.
    fd, tmp_path = tempfile.mkstemp(
        dir=str(config.theo_dir), prefix=".state-", suffix=".tmp"
    )
    try:
        # Close the fd from mkstemp first, then write via Path.
        os.close(fd)
        Path(tmp_path).write_text(payload, encoding="utf-8")
        Path(tmp_path).replace(config.state_file)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise

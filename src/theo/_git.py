"""Git helpers for Theo."""

from __future__ import annotations

import subprocess
from pathlib import Path


def head_commit(cwd: Path | None = None) -> str | None:
    """Return current HEAD commit hash, or None if not in a git repo."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.stdout.strip() if result.returncode == 0 else None


_MAX_WALK_DEPTH = 100


def find_theo_root(start: Path) -> Path | None:
    """Walk upward from *start* to find a directory containing ``.theo/config.json``.

    Guards against circular symlinks by tracking visited directories and
    enforcing a maximum traversal depth of :data:`_MAX_WALK_DEPTH` levels.
    """
    current = start.resolve()
    seen: set[Path] = set()
    for _ in range(_MAX_WALK_DEPTH):
        if current in seen:
            return None
        seen.add(current)
        if (current / ".theo" / "config.json").is_file():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None

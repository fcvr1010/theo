"""
Commit a copy-on-write (COW) session by atomically replacing the main DB.

    commit_write(cow_path, db_path) -> dict

Uses os.rename() for an atomic same-filesystem rename.  Cleans up any
leftover sidecar files (.bak, .stale, old COW WAL files).

Returns: {status: "ok", cow_path: str, db_path: str}
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from theo import get_logger

_log = get_logger("commit_write")


def commit_write(cow_path: str, db_path: str) -> dict[str, Any]:
    cow = Path(cow_path)
    main = Path(db_path)

    if not cow.exists():
        raise FileNotFoundError(f"COW file does not exist: {cow_path}")

    _log.info("[WRITE] Commit COW session: %s -> %s", cow_path, db_path)

    # Atomic rename (same filesystem guaranteed by begin_write).
    os.rename(str(cow), str(main))

    db_dir = main.parent

    # Move any COW sidecar files (WAL, lock) to main sidecar names.
    for sidecar in list(db_dir.glob(f"{cow.name}.*")):
        suffix = sidecar.name[len(cow.name) :]  # e.g. ".wal"
        target = db_dir / f"{main.name}{suffix}"
        os.rename(str(sidecar), str(target))

    # Clean up stale/backup files.
    for pattern in (f"{main.name}*.bak", f"{main.name}*.stale"):
        for f in db_dir.glob(pattern):
            f.unlink(missing_ok=True)

    return {"status": "ok", "cow_path": cow_path, "db_path": db_path}


if __name__ == "__main__":
    import json
    import sys

    cow_path = sys.argv[1]
    db_path = sys.argv[2]
    print(json.dumps(commit_write(cow_path, db_path), indent=2))

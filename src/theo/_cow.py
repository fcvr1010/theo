"""Copy-on-Write lifecycle for KuzuDB database files.

KuzuDB stores data in a single ``.db`` file with an optional ``.db.wal``
sidecar.  The COW pattern copies both files to a temporary location, applies
mutations to the copy, and atomically renames the copy back on success.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


def begin_write(db_path: Path) -> Path:
    """Copy *db_path* (and its WAL sidecar, if present) to a temp path.

    Returns the temporary database path.
    """
    tmp_path = db_path.parent / f"{db_path.name}.tmp.{uuid.uuid4().hex}"
    shutil.copy2(db_path, tmp_path)
    wal = Path(str(db_path) + ".wal")
    if wal.exists():
        shutil.copy2(wal, Path(str(tmp_path) + ".wal"))
    return tmp_path


def commit_write(tmp_path: Path, db_path: Path) -> None:
    """Atomically promote *tmp_path* to *db_path*."""
    os.rename(tmp_path, db_path)
    tmp_wal = Path(str(tmp_path) + ".wal")
    db_wal = Path(str(db_path) + ".wal")
    if tmp_wal.exists():
        os.rename(tmp_wal, db_wal)
    elif db_wal.exists():
        # Tmp had no WAL but the original did -- remove stale WAL
        db_wal.unlink()


def abort_write(tmp_path: Path) -> None:
    """Remove temporary files after a failed write."""
    tmp_path.unlink(missing_ok=True)
    tmp_wal = Path(str(tmp_path) + ".wal")
    tmp_wal.unlink(missing_ok=True)

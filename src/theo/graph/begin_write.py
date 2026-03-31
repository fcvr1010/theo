"""
Begin a copy-on-write (COW) session for the Theo graph database.

    begin_write(db_path) -> str

Copies the main DB to a temporary COW file so the writer can work on it
without blocking concurrent readers.  Cleans up stale COW files older than
2 hours (no indexer run should take longer than ~30 minutes).

Returns: the absolute path to the temporary COW database.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from theo import get_logger

_log = get_logger("begin_write")

# COW files older than this are considered stale and will be cleaned up.
STALE_THRESHOLD_SECONDS = 2 * 60 * 60  # 2 hours


def _cleanup_stale_cow_files(db_dir: Path, db_name: str) -> None:
    """Remove .cow_<id> files that are older than the staleness threshold."""
    cow_prefix = f"{db_name}.cow_"
    now = time.time()
    # Collect unique COW IDs first, then decide which to remove.
    cow_ids: set[str] = set()
    for f in db_dir.iterdir():
        if not f.name.startswith(cow_prefix):
            continue
        # Extract ID from the base cow file (ignore sidecar suffixes like .wal).
        # Pattern: {db_name}.cow_{id} or {db_name}.cow_{id}.wal
        after_prefix = f.name[len(cow_prefix) :]
        cow_id = after_prefix.split(".")[0]
        if cow_id:
            cow_ids.add(cow_id)

    for cow_id in cow_ids:
        cow_base = db_dir / f"{db_name}.cow_{cow_id}"
        # Use the base COW file's mtime to determine age.
        age = now - cow_base.stat().st_mtime if cow_base.exists() else STALE_THRESHOLD_SECONDS + 1

        if age > STALE_THRESHOLD_SECONDS:
            for sidecar in db_dir.glob(f"{db_name}.cow_{cow_id}*"):
                _log.info("Removing stale COW file: %s (age=%.0fs)", sidecar, age)
                sidecar.unlink(missing_ok=True)


def begin_write(db_path: str) -> str:
    main = Path(db_path)
    db_dir = main.parent
    db_name = main.name  # e.g. "code-index.db"

    db_dir.mkdir(parents=True, exist_ok=True)

    # Clean up stale COW files from previous sessions.
    _cleanup_stale_cow_files(db_dir, db_name)

    cow_id = uuid.uuid4().hex[:12]
    cow_path = db_dir / f"{db_name}.cow_{cow_id}"

    if cow_path.exists():
        _log.warning("COW file already exists (UUID collision?): %s -- removing it", cow_path)
        for f in db_dir.glob(f"{cow_path.name}*"):
            f.unlink(missing_ok=True)

    if main.exists():
        shutil.copy2(str(main), str(cow_path))
        # Copy sidecar files (WAL, lock) if they exist.
        for sidecar in db_dir.glob(f"{main.name}.*"):
            if sidecar == main or ".cow_" in sidecar.name:
                continue
            suffix = sidecar.name[len(main.name) :]  # e.g. ".wal"
            dest = db_dir / f"{cow_path.name}{suffix}"
            shutil.copy2(str(sidecar), str(dest))
    # If main DB does not exist yet (first run), the caller will run init_db
    # on the returned cow_path to create a fresh database.

    _log.info("[WRITE] Begin COW session: %s", cow_path)
    return str(cow_path)


if __name__ == "__main__":
    import sys

    print(begin_write(sys.argv[1]))

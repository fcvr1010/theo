"""
Compare indexed SourceFile nodes against actual source files on disk.

    get_coverage(db_path, repo_root, source_dirs=None, extensions=None) -> dict

source_dirs: directories to scan (default: auto-discover from git or scan repo root).
extensions: file extensions to include (default: .py, .js, .ts, .rs, .go, .java, .md).

Returns: {total: int, indexed: int, coverage_pct: float, unindexed: list[str]}
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import real_ladybug as lb

from theo._shared._ext import execute, get_next_list

_DEFAULT_EXTENSIONS = {".py", ".js", ".ts", ".rs", ".go", ".java", ".md"}
_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".tox"}


def _discover_source_dirs(repo_root: Path) -> list[str]:
    """Auto-discover top-level directories from git, excluding hidden/infra dirs."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-tree", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        entries = result.stdout.strip().splitlines()
        dirs = [e for e in entries if (repo_root / e).is_dir() and not e.startswith(".")]
        return dirs if dirs else ["."]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not a git repo or git not available -- scan from root.
        return ["."]


def get_coverage(
    db_path: str,
    repo_root: str,
    source_dirs: list[str] | None = None,
    extensions: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    exts = extensions if extensions is not None else _DEFAULT_EXTENSIONS

    # Resolve source directories.
    dirs_to_scan = source_dirs if source_dirs is not None else _discover_source_dirs(root)

    # Collect all source files on disk.
    on_disk: set[str] = set()
    for src_dir_name in dirs_to_scan:
        src_dir = root / src_dir_name
        if not src_dir.is_dir():
            continue
        for f in src_dir.rglob("*"):
            if f.is_file() and f.suffix in exts:
                rel = str(f.relative_to(root))
                if not any(skip in rel.split("/") for skip in _SKIP_DIRS):
                    on_disk.add(rel)

    # Query indexed files from the graph.
    db = lb.Database(db_path, read_only=True)
    conn = lb.Connection(db)
    qr = execute(conn, "MATCH (f:SourceFile) RETURN f.path")
    indexed: set[str] = set()
    while qr.has_next():
        row = get_next_list(qr)
        indexed.add(str(row[0]))
    del conn
    db.close()

    total = len(on_disk)
    indexed_count = len(indexed & on_disk)
    pct = round((indexed_count / total) * 100, 1) if total > 0 else 100.0
    unindexed = sorted(on_disk - indexed)

    return {
        "total": total,
        "indexed": indexed_count,
        "coverage_pct": pct,
        "unindexed": unindexed,
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: get_coverage.py <db_path> <repo_root> "
            "[--source-dirs dir1,dir2] [--extensions .py,.js,.ts]",
            file=sys.stderr,
        )
        sys.exit(1)

    db_path = sys.argv[1]
    repo_root = sys.argv[2]

    cli_source_dirs: list[str] | None = None
    cli_extensions: set[str] | None = None

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == "--source-dirs" and i + 1 < len(sys.argv):
            cli_source_dirs = sys.argv[i + 1].split(",")
            i += 2
        elif sys.argv[i] == "--extensions" and i + 1 < len(sys.argv):
            cli_extensions = set(sys.argv[i + 1].split(","))
            i += 2
        else:
            i += 1

    result = get_coverage(
        db_path,
        repo_root,
        source_dirs=cli_source_dirs,
        extensions=cli_extensions,
    )
    print(json.dumps(result, indent=2))

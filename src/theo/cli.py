"""Theo CLI entry point.

    theo [command] [options]

Commands:
  add <url-or-path>   Register and clone a repository for indexing
  remove <slug>       Remove a tracked repository
  list                List all monitored repositories
  stats [slug]        Show indexing statistics
"""

from __future__ import annotations

import contextlib
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from theo import __version__
from theo.config import TheoConfig
from theo.repo_manager import (
    GitOperationError,
    RepoEntry,
    RepoManager,
    RepoNotFoundError,
)
from theo.tools.get_coverage import get_coverage
from theo.tools.init_db import init_db
from theo.tools.node_counts import get_node_counts

_USAGE = f"""\
theo {__version__} -- codebase intelligence agent

Usage:
  theo --version                          Show version
  theo --help                             Show this help
  theo add <url-or-path>                  Add a repository (URL or local path)
  theo remove <path-or-slug> [--delete-data]  Remove a watched repository
  theo list                               List monitored repositories
  theo stats [path-or-slug]               Show indexing statistics
"""

# Regex for SCP-style SSH URLs: git@host:path
_SCP_RE = re.compile(r"^[\w.-]+@[\w.-]+:.+$")


def _is_url(target: str) -> bool:
    """Return True if *target* looks like a URL rather than a local path."""
    if "://" in target:
        return True
    return bool(_SCP_RE.match(target))


def _cmd_add(
    args: list[str],
    config: TheoConfig,
    manager: RepoManager,
) -> int:
    """Handle ``theo add <url-or-path>``."""
    if not args:
        print("Error: 'add' requires a URL or path argument.", file=sys.stderr)
        return 1

    target = args[0]
    rest = args[1:]

    if rest:
        print(f"Error: unknown option '{rest[0]}'.", file=sys.stderr)
        return 1

    # Determine URL vs local path.
    if _is_url(target):
        url = target
    else:
        resolved = Path(target).resolve()
        if not resolved.exists():
            print(f"Error: local path does not exist: {resolved}", file=sys.stderr)
            return 1
        url = f"file://{resolved}"

    try:
        entry = manager.add(url)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Clone the repository.
    try:
        manager.clone(entry.slug)
    except GitOperationError as exc:
        # Roll back the tracking entry on clone failure.
        with contextlib.suppress(RepoNotFoundError):
            manager.remove(entry.slug)
        print(f"Error: clone failed -- {exc}", file=sys.stderr)
        return 1

    # Initialise the database.
    init_db(entry.db_path)

    print(f"Added: {entry.slug}")
    print(f"  URL:    {entry.url}")
    print(f"  Clone:  {entry.clone_path}")
    print(f"  DB:     {entry.db_path}")
    return 0


def _cmd_remove(
    args: list[str],
    config: TheoConfig,
    manager: RepoManager,
) -> int:
    """Handle ``theo remove <path-or-slug> [--delete-data]``."""
    if not args:
        print("Error: 'remove' requires a path or slug argument.", file=sys.stderr)
        return 1

    target = args[0]
    rest = args[1:]

    # Validate flags.
    delete_data = False
    for flag in rest:
        if flag == "--delete-data":
            delete_data = True
        else:
            print(f"Error: unknown option '{flag}'.", file=sys.stderr)
            return 1

    # Look up the entry first (before removing).
    try:
        entry = manager.get(target)
    except RepoNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if delete_data:
        # Prompt for confirmation if stdin is a TTY.
        if sys.stdin.isatty():
            answer = input(f"Delete clone ({entry.clone_path}) and DB ({entry.db_path})? [y/N] ")
            if answer.strip().lower() != "y":
                print("Aborted. Data and tracking entry kept.")
                return 0

        # User confirmed (or non-interactive): remove tracking, then delete data.
        manager.remove(target)

        clone_path = Path(entry.clone_path)
        db_path = Path(entry.db_path)
        if clone_path.exists():
            shutil.rmtree(clone_path)
        if db_path.exists():
            if db_path.is_dir():
                shutil.rmtree(db_path)
            else:
                db_path.unlink()
        print(f"Removed: {entry.slug} (tracking entry + data deleted)")
    else:
        manager.remove(target)
        print(f"Removed: {entry.slug} (tracking entry only)")

    return 0


def _cmd_list(
    args: list[str],
    config: TheoConfig,
    manager: RepoManager,
) -> int:
    """Handle ``theo list``."""
    entries = manager.list()
    if not entries:
        print("No repositories registered. Use 'theo add <url>' to add one.")
        return 0

    for entry in entries:
        coverage_str = _get_coverage_str(entry)
        last_run = entry.last_run_at or "never"
        print(f"  {entry.slug}")
        print(f"    URL:      {entry.url}")
        print(f"    DB:       {entry.db_path}")
        print(f"    Coverage: {coverage_str}")
        print(f"    Last run: {last_run}")
    return 0


def _get_coverage_str(entry: RepoEntry) -> str:
    """Return a human-readable coverage string for a repo entry.

    Returns 'N/A' if the DB or clone directory does not exist.
    """
    db_exists = Path(entry.db_path).exists()
    clone_exists = Path(entry.clone_path).exists()
    if not db_exists or not clone_exists:
        return "N/A"
    try:
        cov = get_coverage(entry.db_path, entry.clone_path)
        return f"{cov['coverage_pct']}% ({cov['indexed']}/{cov['total']} files)"
    except Exception:
        return "N/A"


def _print_entry_stats(entry: RepoEntry) -> None:
    """Print detailed stats for a single repo entry."""
    print(f"  {entry.slug}")
    print(f"    URL:       {entry.url}")
    print(f"    Clone:     {entry.clone_path}")
    print(f"    DB:        {entry.db_path}")
    print(f"    Last SHA:  {entry.last_checked_revision or 'none'}")
    print(f"    Last run:  {entry.last_run_at or 'never'}")

    db_exists = Path(entry.db_path).exists()
    clone_exists = Path(entry.clone_path).exists()

    if db_exists and clone_exists:
        coverage_str = _get_coverage_str(entry)
        print(f"    Coverage:  {coverage_str}")
        try:
            counts = get_node_counts(entry.db_path)
            print(f"    Concepts:  {counts['concepts']}")
            print(f"    Files:     {counts['source_files']}")
        except Exception:
            print("    Concepts:  N/A")
            print("    Files:     N/A")
    else:
        missing = []
        if not clone_exists:
            missing.append("clone")
        if not db_exists:
            missing.append("database")
        print(f"    Coverage:  N/A (missing: {', '.join(missing)})")


def _cmd_stats(
    args: list[str],
    config: TheoConfig,
    manager: RepoManager,
) -> int:
    """Handle ``theo stats [path-or-slug]``."""
    if args:
        target = args[0]
        try:
            entry = manager.get(target)
        except RepoNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        _print_entry_stats(entry)
    else:
        entries = manager.list()
        if not entries:
            print("No repositories registered. Use 'theo add <url>' to add one.")
            return 0
        for entry in entries:
            _print_entry_stats(entry)
    return 0


def main(argv: list[str] | None = None, config: TheoConfig | None = None) -> int:
    """CLI entry point. Returns exit code."""
    args = argv if argv is not None else sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(_USAGE)
        return 0

    if "--version" in args or args[0] == "version":
        print(f"theo {__version__}")
        return 0

    cfg = config or TheoConfig()
    cfg.ensure_dirs()
    manager = RepoManager(cfg)

    cmd = args[0]
    cmd_args = args[1:]

    _CmdHandler = Callable[[list[str], TheoConfig, RepoManager], int]
    handlers: dict[str, _CmdHandler] = {
        "add": _cmd_add,
        "remove": _cmd_remove,
        "list": _cmd_list,
        "stats": _cmd_stats,
    }

    if cmd in handlers:
        return handlers[cmd](cmd_args, cfg, manager)

    print(f"Error: unknown command '{cmd}'. Run 'theo --help' for usage.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

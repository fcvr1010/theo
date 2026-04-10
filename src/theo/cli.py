"""Theo CLI -- codebase intelligence for agentic coding tools.

Commands:
    theo --version       Print version and exit.
    theo init [path]     Initialise a Theo graph in a project directory.
    theo stats           Show graph statistics for the current project.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from theo import __version__


def _cmd_init(args: argparse.Namespace) -> int:
    """Initialise Theo in a project directory."""
    from theo.config import TheoConfig
    from theo.state import TheoState, save_state
    from theo.tools.init_db import init_db

    project_dir = Path(args.path).resolve()
    config = TheoConfig(project_dir=project_dir)

    # Idempotent: if already initialised, say so and exit cleanly.
    if config.theo_dir.exists():
        print(f"Theo already initialised in {project_dir}")
        return 0

    config.ensure_dirs()
    init_db(config.db_path)

    project_name = project_dir.name
    state = TheoState(project=project_name)
    save_state(config, state)

    print(f"Theo initialised in {project_dir}")
    print(f"Graph DB: {config.db_path}")
    print("Next: add the Theo skill file to your project -- see https://github.com/fcvr1010/theo")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    """Show graph statistics for the current project."""
    from theo.config import TheoConfig
    from theo.state import load_state
    from theo.tools.get_coverage import get_coverage
    from theo.tools.node_counts import get_node_counts

    project_dir = Path.cwd()
    config = TheoConfig(project_dir=project_dir)

    if not config.theo_dir.exists():
        print("Theo not initialised in this directory. Run `theo init` first.", file=sys.stderr)
        return 1

    state = load_state(config)
    counts = get_node_counts(config.db_path)
    cov = get_coverage(config.db_path, str(project_dir))

    total_nodes = counts["concepts"] + counts["source_files"]
    if state.last_indexed_commit and state.last_indexed_at:
        last_indexed = f"{state.last_indexed_commit} at {state.last_indexed_at}"
    else:
        last_indexed = "never"

    print(f"Project:          {state.project}")
    print(f"Last indexed:     {last_indexed}")
    print(
        f"Nodes:            {total_nodes} ({counts['concepts']} Concept, "
        f"{counts['source_files']} SourceFile)"
    )
    print(f"Coverage:         {cov['coverage_pct']}%")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="theo",
        description="Theo -- codebase intelligence for agentic coding tools.",
    )
    parser.add_argument("--version", action="version", version=f"theo {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # theo init [path]
    init_parser = subparsers.add_parser("init", help="Initialise Theo in a project directory")
    init_parser.add_argument("path", nargs="?", default=".", help="Project directory (default: .)")

    # theo stats
    subparsers.add_parser("stats", help="Show graph statistics for the current project")

    args = parser.parse_args()

    if args.command == "init":
        return _cmd_init(args)
    elif args.command == "stats":
        return _cmd_stats(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""Theo CLI entry point.

    theo [command] [options]

Stub implementation -- prints version and usage for now.
"""

from __future__ import annotations

import sys

from theo import __version__

_USAGE = f"""\
theo {__version__} -- codebase intelligence agent

Usage:
  theo --version          Show version
  theo --help             Show this help
  theo add <path>         Add a repository to watch (stub)
  theo remove <path>      Remove a watched repository (stub)
  theo stats [path]       Show indexing statistics (stub)
  theo daemon start       Start the background daemon (stub)
  theo daemon stop        Stop the background daemon (stub)
  theo daemon status      Show daemon status (stub)
"""


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    args = argv if argv is not None else sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(_USAGE)
        return 0

    if "--version" in args or args[0] == "version":
        print(f"theo {__version__}")
        return 0

    cmd = args[0]

    if cmd == "add":
        if len(args) < 2:
            print("Error: 'add' requires a path argument.", file=sys.stderr)
            return 1
        print(f"[stub] Would add repository: {args[1]}")
        return 0

    if cmd == "remove":
        if len(args) < 2:
            print("Error: 'remove' requires a path argument.", file=sys.stderr)
            return 1
        print(f"[stub] Would remove repository: {args[1]}")
        return 0

    if cmd == "stats":
        path = args[1] if len(args) > 1 else "."
        print(f"[stub] Would show stats for: {path}")
        return 0

    if cmd == "daemon":
        if len(args) < 2:
            print("Error: 'daemon' requires a subcommand (start|stop|status).", file=sys.stderr)
            return 1
        sub = args[1]
        if sub in ("start", "stop", "status"):
            print(f"[stub] Would execute: daemon {sub}")
            return 0
        print(f"Error: unknown daemon subcommand '{sub}'.", file=sys.stderr)
        return 1

    print(f"Error: unknown command '{cmd}'. Run 'theo --help' for usage.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Theo CLI entry point.

    theo [command] [options]

Commands:
  add <url-or-path>   Register and clone a repository for indexing (stub)
  remove <slug>       Remove a tracked repository (stub)
  list                List all monitored repositories (stub)
  stats [slug]        Show indexing statistics (stub)
  daemon start        Start the background daemon
  daemon stop         Stop the background daemon
  daemon status       Show daemon status
"""

from __future__ import annotations

import sys

from theo import __version__

_USAGE = f"""\
theo {__version__} -- codebase intelligence agent

Usage:
  theo --version                          Show version
  theo --help                             Show this help
  theo add <path>                         Add a repository to watch (stub)
  theo remove <path>                      Remove a watched repository (stub)
  theo list                               List monitored repositories (stub)
  theo stats [path]                       Show indexing statistics (stub)
  theo daemon start [--foreground]        Start the background daemon
  theo daemon stop                        Stop the background daemon
  theo daemon status                      Show daemon status
"""


def _cmd_daemon(args: list[str]) -> int:
    """Handle ``theo daemon <start|stop|status>``."""
    # Lazy imports to avoid pulling in heavy modules for --help / --version.
    from theo.config import TheoConfig
    from theo.daemon import Daemon, DaemonError
    from theo.repo_manager import RepoManager

    if not args:
        print("Error: 'daemon' requires a subcommand (start|stop|status).", file=sys.stderr)
        return 1

    sub = args[0]
    rest = args[1:]

    cfg = TheoConfig()
    cfg.ensure_dirs()
    manager = RepoManager(cfg)
    daemon = Daemon(cfg, manager)

    if sub == "start":
        foreground = "--foreground" in rest
        try:
            if foreground:
                import os

                print(f"Daemon running in foreground (pid={os.getpid()})")
                daemon.run_foreground()
            else:
                daemon.start()
                print("Daemon started.")
        except DaemonError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if sub == "stop":
        try:
            daemon.stop()
            print("Daemon stopped.")
        except DaemonError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if sub == "status":
        st = daemon.status()
        if st.running:
            print(f"Daemon is running (pid={st.pid})")
        else:
            print("Daemon is not running.")
        return 0

    print(f"Error: unknown daemon subcommand '{sub}'.", file=sys.stderr)
    return 1


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
    cmd_args = args[1:]

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

    if cmd == "list":
        print("[stub] Monitored repositories:")
        print("  <path>  db: <db_path>  coverage: <N>%  last indexed: <timestamp>")
        return 0

    if cmd == "stats":
        path = args[1] if len(args) > 1 else "."
        print(f"[stub] Would show stats for: {path}")
        return 0

    if cmd == "daemon":
        return _cmd_daemon(cmd_args)

    print(f"Error: unknown command '{cmd}'. Run 'theo --help' for usage.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

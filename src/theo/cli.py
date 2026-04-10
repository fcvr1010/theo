"""Theo CLI — codebase intelligence for agentic coding tools.

The full CLI (theo init, theo stats, theo query, etc.) is being built.
"""

from __future__ import annotations

from theo import __version__


def main() -> None:  # pragma: no cover
    print(f"theo {__version__}")
    print("Run `theo --help` after the skill integration CLI is complete.")


if __name__ == "__main__":
    main()

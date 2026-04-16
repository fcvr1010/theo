"""Theo CLI entry point.

Registers the ``use``, ``serve``, ``stats``, ``reload``, and ``ui`` subcommands.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="theo",
    help="Theo -- codebase intelligence.  Build a living knowledge graph of your repository.",
    no_args_is_help=True,
)


@app.command()
def use(
    project_dir: str = typer.Argument(
        ".",
        help="Path to the project directory to initialise (defaults to cwd).",
    ),
) -> None:
    """Initialise Theo in a project directory."""
    from theo.cli.use import run

    run(project_dir)


@app.command()
def serve(
    project_dir: str = typer.Argument(
        ".",
        help="Path to the project directory (defaults to cwd).",
    ),
) -> None:
    """Start the Theo MCP server (stdio transport)."""
    from theo.cli.serve import run

    run(project_dir)


@app.command()
def stats(
    project_dir: str = typer.Argument(
        ".",
        help="Path to the project directory (defaults to cwd).",
    ),
) -> None:
    """Print graph statistics and freshness info."""
    from theo.cli.stats import run

    run(project_dir)


@app.command()
def reload(
    project_dir: str = typer.Argument(
        ".",
        help="Path to the project directory (defaults to cwd).",
    ),
) -> None:
    """Rebuild the runtime DB from the on-disk CSV files."""
    from theo.cli.reload import run

    run(project_dir)


@app.command()
def ui(
    project_dir: str = typer.Argument(
        ".",
        help="Path to the project directory (defaults to cwd).",
    ),
    port: int = typer.Option(7777, help="Port to serve on."),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Don't open browser automatically."
    ),
) -> None:
    """Start the Theo graph visualization server."""
    from theo.cli.ui import run

    run(project_dir, port=port, no_browser=no_browser)

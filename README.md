# Theo

Theo is a persistent, accumulating knowledge graph of a software codebase. It lives inside the repository itself (as CSV files committed to git) and is designed to be embedded inside a coding agent's session via MCP. Theo captures architecture, interfaces, dependencies, criticality, and complexity -- annotated with contextual notes that survive across sessions, collaborators, and branches.

## How it works

Run `theo use` in a project directory to register Theo's MCP server and install skill files. From that point on, every Claude Code (or Cursor, or Codex) session in that project has access to Theo's tools for querying and updating the knowledge graph.

Note that it is still your agentic coding tool's choice whether to use Theo or not. If you want to "force usage", ask about theo explicitly in your prompt, or use the `/theo` command.

The graph is stored in two layers:

- **CSV files** (`.theo/*.csv`) -- the portable, version-controlled representation. These are committed to git and are the source of truth.
- **LadybugDB database** (`.theo/db/theo.db`) -- the queryable runtime store, gitignored and rebuilt from CSVs as needed.

## Installation

Theo is not yet published to PyPI, so install it directly from a local clone using `uv tool`. This puts the `theo` command on your `PATH` (typically under `~/.local/bin`) while keeping it tied to this checkout.

```bash
# From the root of your local theo clone
uv tool install --force .
```

`--force` lets the command double as a re-install, which is what you want whenever you pull new changes or switch branches:

If you prefer `theo` to pick up local edits without reinstalling, add `--editable`:

```bash
uv tool install --force --editable .
```

To include optional extras (e.g. the UI or semantic search):

```bash
uv tool install --force --editable ".[ui,semantic]"
```

To remove the tool:

```bash
uv tool uninstall theo
```

For development work on Theo itself (running the test suite, linters, etc.), sync the dev environment with `uv sync --all-extras` -- see [Development](#development) below.

## Quick start

The simplest way is to run `theo use` in the root of your project/worktree. Alternatively,

```bash
theo use /path/to/your/project
```

`theo use` creates the `.theo/` directory, sets up the database, writes skill files and registers the MCP server for Claude Code, Codex, and Cursor.

## UI

Theo includes a simple visual browser for the graph. Install theo with the optional ui package and then run

```bash
theo ui
```

in your project directory. The server will be available at <http://127.0.0.1:7777>

## Development

```bash
uv sync --all-extras           # Set up the dev environment
uv run pytest                  # Run the test suite
uv run ruff check .            # Lint
uv run ruff format --check .   # Check formatting
uv run mypy src/               # Type check
```

## License

Apache-2.0

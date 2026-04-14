# Theo

Theo is a persistent, accumulating knowledge graph of a software codebase. It lives inside the repository itself (as CSV files committed to git) and is designed to be embedded inside a coding agent's session via MCP. Theo captures architecture, interfaces, dependencies, criticality, and complexity -- annotated with contextual notes that survive across sessions, collaborators, and branches.

## How it works

Run `theo use` in a project directory to register Theo's MCP server and install skill files. From that point on, every Claude Code (or Cursor, or Codex) session in that project has access to Theo's tools for querying and updating the knowledge graph.

Note that it is still your agentic coding tool's choice whether to use Theo or not. If you want to "force usage", ask about theo explicitly in your prompt, or use the `/theo` command.

The graph is stored in two layers:

- **CSV files** (`.theo/*.csv`) -- the portable, version-controlled representation. These are committed to git and are the source of truth.
- **LadybugDB database** (`.theo/db/theo.db`) -- the queryable runtime store, gitignored and rebuilt from CSVs as needed.

## Installation

```bash
uv pip install -e ".[dev]"
```

## Quick start

```bash
# Initialise Theo in your project
theo use /path/to/your/project

# Check graph health
theo stats /path/to/your/project

# Start the MCP server (usually invoked automatically by Claude Code/Cursor/Codex)
theo serve
```

`theo use` creates the `.theo/` directory, sets up the database, writes skill files to `.claude/skills/theo/` (and `.agents/skills/theo/` for Cursor compatibility), and registers the MCP server in both `.mcp.json` (Claude Code / Cursor) and `.codex/config.toml` (Codex).

## Development

```bash
uv run pytest                  # Run the test suite
uv run ruff check .            # Lint
uv run ruff format --check .   # Check formatting
uv run mypy src/               # Type check
```

## License

Apache-2.0

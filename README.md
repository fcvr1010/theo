# Theo

Codebase intelligence agent — builds a living knowledge graph of any software repository.

Theo is invoked via a skill file committed to your project. See [skill file setup](https://github.com/fcvr1010/theo/wiki/skill-file-setup) for integration with Claude Code and Cursor.

## Schema

Theo uses [KuzuDB](https://kuzudb.com/) as its graph database with this schema:

**Node types:**

- **Concept** — high-level logical units (modules, subsystems, features); primary key: `id`
- **SourceFile** — individual source files; primary key: `path`

**Relationship types:**

- **PartOf** (Concept → Concept) — hierarchical containment
- **BelongsTo** (SourceFile → Concept) — file-to-concept membership
- **DependsOn** (Concept → Concept) — dependency between concepts
- **InteractsWith** (Concept → Concept) — interaction between concepts
- **Imports** (SourceFile → SourceFile) — file-level import relationships

All node tables include an `embedding FLOAT[768]` column for semantic search
(powered by [nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)
via [fastembed](https://github.com/qdrant/fastembed)).

## Installation

```bash
# Install with uv
uv sync

# Install with dev dependencies (for testing, linting, type checking)
uv sync --extra dev
```

## Quick start

```python
from theo.tools import init_db, upsert_node, upsert_rel
from theo.client import query

# Create and initialise a database
init_db(".theo/db")

# Add nodes
upsert_node(".theo/db", "Concept", {"id": "auth", "name": "Authentication"})
upsert_node(".theo/db", "SourceFile", {"path": "src/auth.py", "name": "auth.py"})

# Add a relationship
upsert_rel(".theo/db", "BelongsTo", "SourceFile", "src/auth.py", "Concept", "auth")

# Query the graph (read-only, first arg is the db path)
results = query(".theo/db", "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept) RETURN f.path, c.name")
```

For direct database path access (e.g. COW copies during write sessions), use `theo.tools.query`:

```python
from theo.tools.query import query as tools_query

# Accepts a db_path directly; supports optional read_only=False for mutations.
rows = tools_query("/path/to/cow-copy.db", "MATCH (c:Concept) RETURN c.id")
```

## Running tests

```bash
# Unit tests (fast, no model download)
uv run pytest tests/ -v -m "not integration"

# All tests including integration (requires ~200 MB model download on first run)
uv run pytest tests/ -v
```

## License

Apache 2.0

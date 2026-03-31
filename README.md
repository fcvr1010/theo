# Theo

Codebase intelligence agent — builds a living knowledge graph of any software repository.

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
from theo.graph import init_db, upsert_node, upsert_rel, query

# Create and initialise a database
init_db("my-graph.db")

# Add nodes
upsert_node("my-graph.db", "Concept", {"id": "auth", "name": "Authentication"})
upsert_node("my-graph.db", "SourceFile", {"path": "src/auth.py", "name": "auth.py"})

# Add a relationship
upsert_rel("my-graph.db", "BelongsTo", "SourceFile", "src/auth.py", "Concept", "auth")

# Query the graph
results = query("my-graph.db", "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept) RETURN f.path, c.name")
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

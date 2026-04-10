# Theo: Codebase Intelligence (Cursor Rules)

This project uses Theo to maintain a semantic knowledge graph in `.theo/db/`.
Query it before making architectural changes, touching unfamiliar subsystems, or refactoring.

## Quick start

Initialise the database (idempotent):

```bash
python -m theo.tools.init_db .theo/db
```

Check freshness:

```bash
python -m theo.tools.get_coverage .theo/db .
```

If `last_revision` matches `git rev-parse HEAD`, the graph is up to date.

## Querying

**Semantic search (natural language):**

```bash
python -m theo.client.semantic_search .theo/db "authentication and session management"
python -m theo.client.semantic_search .theo/db "how are errors handled" Concept 5 true
```

**Cypher queries:**

```bash
# All subsystems
python -m theo.tools.query .theo/db "MATCH (n:Concept) WHERE n.kind IN ['system','subsystem'] RETURN n.name, n.kind, n.level, n.description ORDER BY n.level, n.name"

# Files in a component
python -m theo.tools.query .theo/db "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept {name: 'ComponentName'}) RETURN f.path, f.description ORDER BY f.path"

# Component notes (deep architectural intelligence)
python -m theo.tools.query .theo/db "MATCH (n:Concept {name: 'ComponentName'}) RETURN n.notes"

# Cross-component interactions
python -m theo.tools.query .theo/db "MATCH (a:Concept)-[r:InteractsWith|DependsOn]->(b:Concept) RETURN a.name, type(r), b.name, r.description"
```

## When to skip

Skip Theo for typo fixes, documentation-only changes, and files you just indexed this session.

## Indexing

When the graph is empty or stale, it needs to be re-indexed using the Architect Lens.
Full indexing instructions are in `src/theo/lenses/architect_prompt.md` in the theo package.
The key rule: always use the Copy-on-Write workflow (`begin_write` / `commit_write`) and tag every node with `"git_revision": "<HEAD_SHA>"`.

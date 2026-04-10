This is the Theo slash command. When invoked, analyse the graph state and either query it (if the user's request is about understanding the codebase) or update it (if it's stale or explicitly requested).

Theo maintains a semantic knowledge graph of this codebase in `.theo/db/`. Use this command to query the graph for architectural context or to trigger indexing when the graph is stale.

## Checklist

Run these steps in order:

### 1. Initialise (idempotent)

```bash
python -m theo.tools.init_db .theo/db
```

### 2. Check freshness

```bash
python -m theo.tools.get_coverage .theo/db .
# Interpret output:
# - "indexed": 0  → graph is empty, run the indexing workflow
# - "stale": [..] → those files changed since last index, run incremental re-indexing
# - "stale": []   → graph is fresh, proceed to querying
```

- If `indexed` is 0: the graph is empty -- run the indexing workflow (see below).
- If `stale` is non-empty: those files need re-indexing -- run incremental re-indexing.
- If `stale` is empty: the graph is fresh -- proceed to querying.

### 3. Query or index

**If the user asked about understanding the codebase**, query the graph using the tools below.

**If the graph is stale or the user asked to update it**, run the Architect Lens indexing workflow using the COW protocol.

## Tool quick reference

| Action | Command |
|--------|---------|
| Semantic search | `python -m theo.client.semantic_search .theo/db "<query>" [Table] [top_k] [expand]` |
| Cypher query | `python -m theo.tools.query .theo/db "<cypher>"` |
| List subsystems | `python -m theo.tools.query .theo/db "MATCH (n:Concept) WHERE n.kind IN ['system','subsystem'] RETURN n.name, n.kind, n.level, n.description ORDER BY n.level, n.name"` |
| Files in component | `python -m theo.tools.query .theo/db "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept {name: '<Name>'}) RETURN f.path, f.description ORDER BY f.path"` |
| Component notes | `python -m theo.tools.query .theo/db "MATCH (n:Concept {name: '<Name>'}) RETURN n.notes"` |
| Init DB | `python -m theo.tools.init_db .theo/db` |
| Begin COW write | `COW_PATH=$(python -m theo.tools.begin_write .theo/db)` |
| Upsert node | `python -m theo.tools.upsert_node $COW_PATH <Table> '<json>'` |
| Upsert relationship | `python -m theo.tools.upsert_rel $COW_PATH <RelType> <FromTable> <from_id> <ToTable> <to_id>` |
| Commit COW | `python -m theo.tools.commit_write $COW_PATH .theo/db` |
| Rebuild indexes | `python -m theo.tools.manage_indexes .theo/db` |
| Backfill embeddings | `python -m theo.tools.backfill_embeddings .theo/db` |
| Coverage stats | `python -m theo.tools.get_coverage .theo/db .` |

**Interactions query** (separated from the table because the Cypher pipe operator breaks Markdown table syntax):
```bash
python -m theo.tools.query .theo/db "MATCH (a:Concept)-[r:InteractsWith|DependsOn]->(b:Concept) RETURN a.name, type(r), b.name, r.description"
```

## COW write workflow (for indexing)

```bash
# 1. Start COW session
COW_PATH=$(python -m theo.tools.begin_write .theo/db)

# 2. All writes use $COW_PATH
HEAD_SHA=$(git rev-parse HEAD)
python -m theo.tools.init_db $COW_PATH
python -m theo.tools.upsert_node $COW_PATH Concept '{"id": "my-concept", "name": "...", "kind": "system", "level": 1, "description": "...", "notes": "...", "git_revision": "'$HEAD_SHA'"}'

# 3. Validate (run integrity checks), then commit
python -m theo.tools.commit_write $COW_PATH .theo/db

# 4. Backfill embeddings (commit_write already rebuilds vector indexes)
python -m theo.tools.backfill_embeddings .theo/db
```

Every `upsert_node` call MUST include `"git_revision": "<HEAD_SHA>"`.

## Integrity checks (run before commit)

```bash
python -m theo.tools.query $COW_PATH "MATCH (c:Concept) WHERE c.kind <> 'root' AND NOT EXISTS { MATCH (c)-[:PartOf]->(:Concept) } RETURN c.id, c.kind"
python -m theo.tools.query $COW_PATH "MATCH (c:Concept {kind: 'root'})-[:PartOf]->(:Concept) RETURN c.id"
python -m theo.tools.query $COW_PATH "MATCH (child:Concept)-[:PartOf]->(parent:Concept) WHERE child.level <> parent.level + 1 RETURN child.id, child.level, parent.id, parent.level"
python -m theo.tools.query $COW_PATH "MATCH (c:Concept)-[:PartOf]->(p:Concept) WITH c, count(p) AS parents WHERE parents > 1 RETURN c.id, parents"
python -m theo.tools.query $COW_PATH "MATCH (c:Concept)-[:PartOf*2..]->(c) RETURN c.id"
```

All queries must return empty results. Fix violations before committing.

For full indexing instructions (analysis protocol, quality bar, kind definitions, incremental re-indexing), see your CLAUDE.md Theo block or `src/theo/lenses/architect_prompt.md` in the theo package.

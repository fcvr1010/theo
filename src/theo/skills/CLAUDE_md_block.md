# Theo: Codebase Intelligence

<!-- theo-skill-version: 1.0 -->

Theo maintains a semantic knowledge graph of this codebase. Use it before making changes to unfamiliar code, when planning architectural work, and whenever you need to understand how components fit together. All Theo data lives in `.theo/db/` inside this project.

## When to use Theo

**Query the graph before:** any architectural change, touching unfamiliar subsystems, refactoring, understanding how components interact.

**Update the graph after:** significant structural changes, or when `git_revision` is stale (see "Freshness check" below).

**Skip Theo for:** typo fixes, documentation updates, changes in a file you just indexed this session.

## Session start protocol

At the start of any session involving significant code work, run this sequence:

### 1. Check initialisation

```bash
python -m theo.tools.init_db .theo/db
```
*(idempotent -- safe to run every time, creates the DB if it doesn't exist)*

### 2. Check freshness

```bash
git rev-parse HEAD
python -m theo.tools.get_coverage .theo/db .
```

Compare the `last_revision` from `get_coverage` output to the current HEAD.
- If they match: the graph is fresh. **Query it before coding.**
- If they differ or the graph is empty: **run the Architect Lens** (see "Indexing" below) on the changed files before coding.

### 3. Query before coding

Use the querying patterns below to get architectural context before making changes.

## Querying the graph

Use these patterns to get architectural context before making changes:

**Semantic search (natural language):**
```bash
python -m theo.client.semantic_search .theo/db "authentication and session management"
python -m theo.client.semantic_search .theo/db "how are errors handled"
python -m theo.client.semantic_search .theo/db "database write workflow" Concept 5 true
```

**Find all subsystems:**
```bash
python -m theo.tools.query .theo/db "MATCH (n:Concept) WHERE n.kind IN ['system','subsystem'] RETURN n.name, n.kind, n.level, n.description ORDER BY n.level, n.name"
```

**Find files in a component:**
```bash
python -m theo.tools.query .theo/db "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept {name: 'Authentication'}) RETURN f.path, f.description ORDER BY f.path"
```

**Get notes on a specific component:**
```bash
python -m theo.tools.query .theo/db "MATCH (n:Concept {name: 'PaymentService'}) RETURN n.notes"
```

**Find how two components interact:**
```bash
python -m theo.tools.query .theo/db "MATCH (a:Concept)-[r:InteractsWith|DependsOn]->(b:Concept) RETURN a.name, type(r), b.name, r.description"
```

## Indexing (Architect Lens)

Run this when the graph is empty or stale. Follow the complete protocol below.

### Copy-on-Write (COW) workflow -- MANDATORY

You MUST use the COW workflow. Never write directly to `.theo/db`.

```bash
# 1. Start a COW session
COW_PATH=$(python -m theo.tools.begin_write .theo/db)
echo "COW path: $COW_PATH"

# 2. All writes go to $COW_PATH during this session:
python -m theo.tools.init_db $COW_PATH
python -m theo.tools.upsert_node $COW_PATH Concept '{"id": "...", ...}'
python -m theo.tools.upsert_rel $COW_PATH PartOf Concept child-id Concept parent-id

# 3. Validate, then commit atomically:
python -m theo.tools.commit_write $COW_PATH .theo/db

# 4. Rebuild indexes and embeddings:
python -m theo.tools.manage_indexes .theo/db
python -m theo.tools.backfill_embeddings .theo/db
```

### git_revision tagging

Every `upsert_node` call MUST include `"git_revision": "<HEAD_SHA>"`.

```bash
HEAD_SHA=$(git rev-parse HEAD)
```

Use this SHA in every node you write.

### Schema reference

**Concept node** (architectural groupings):
```json
{
  "id": "auth-subsystem",
  "name": "Authentication",
  "kind": "subsystem",
  "level": 2,
  "description": "one sentence",
  "notes": "...",
  "git_revision": "<HEAD_SHA>"
}
```

**SourceFile node:**
```json
{
  "path": "src/auth/session.py",
  "name": "session.py",
  "language": "python",
  "description": "one sentence",
  "notes": "...",
  "line_count": 142,
  "git_revision": "<HEAD_SHA>"
}
```

**Relationships:**
- `PartOf`: Concept -> Concept (hierarchy: child PartOf parent)
- `BelongsTo`: SourceFile -> Concept (file belongs to its closest concept)
- `InteractsWith`: Concept -> Concept (runtime collaboration)
- `DependsOn`: Concept -> Concept (architectural dependency)
- `Imports`: SourceFile -> SourceFile (import relationships)

### Tools reference

All tools live in the `src/theo/tools/` package. Invoke them as Python modules:

| Tool | Usage |
|------|-------|
| `begin_write` | `python -m theo.tools.begin_write <db_path>` -- Start a COW write session (prints temp path) |
| `commit_write` | `python -m theo.tools.commit_write <cow_path> <db_path>` -- Atomically replace main DB with COW copy |
| `init_db` | `python -m theo.tools.init_db <db_path>` -- Create schema (idempotent) |
| `upsert_node` | `python -m theo.tools.upsert_node <db_path> <table> '<json>'` -- MERGE a node |
| `upsert_rel` | `python -m theo.tools.upsert_rel <db_path> <rel_type> <from_table> <from_id> <to_table> <to_id> ['<json>']` -- Create relationship |
| `query` | `python -m theo.tools.query <db_path> '<cypher>'` -- Run a Cypher query |
| `get_coverage` | `python -m theo.tools.get_coverage <db_path> <repo_root>` -- Coverage stats and staleness detection |
| `manage_indexes` | `python -m theo.tools.manage_indexes <db_path>` -- Rebuild full-text and vector indexes |
| `backfill_embeddings` | `python -m theo.tools.backfill_embeddings <db_path>` -- Generate embeddings for nodes missing them |

## Core philosophy

This is **not** a structural cataloging exercise. The focus is high-level architecture, system design, design patterns, conventions, and **meaning**. For every piece of code you index, ask yourself:

- **What is the architectural role of this component?** Not the surface reading, but the actual purpose it serves within the larger system -- how it fits into the decomposition of systems and subsystems.
- **Why is it structured this way?** What architectural decisions shaped this code? What design patterns are being applied (factory, observer, strategy, middleware chain, event bus, etc.)? What trade-offs were made and why?
- **What is the overall architectural style?** Layered, event-driven, hexagonal, microservices, monolith? How is the codebase decomposed into systems and subsystems? What are the system boundaries?
- **What conventions must be followed?** Patterns that aren't enforced by the type system but are critical to architectural consistency (e.g., "all public functions must have type annotations", "atomic writes via .tmp rename", "environment variables are only read in the config module", "all HTTP handlers follow the same middleware chain").
- **What are the non-obvious design decisions?** Architectural choices that look wrong but are intentional, workarounds that exist for structural reasons, patterns that deviate from the project's usual style and why.
- **How do systems interact at a high level?** The architectural interaction patterns -- which systems collaborate, what communication patterns they use (sync calls, async messages, shared state, event dispatch), and how the overall data flow is structured.

## Kind definitions

Each Concept node has a `kind` that describes its architectural nature:

- **`root`** -- The repository itself. There is exactly **one** root node per indexed repository. Level 0. No outgoing `PartOf` edge. The root represents the entire codebase as a single conceptual unit.
- **`system`** -- A major, independently recognisable area within the repository. Think of it as a top-level concern that a new developer would identify when reading the README or scanning the directory tree. **Must have exactly one `PartOf` edge** to the root or to another system.
- **`subsystem`** -- A cohesive sub-area within a system that has internal structure worth modelling. **Must have exactly one `PartOf` edge** to a system or another subsystem.
- **`module`** -- A leaf-level unit mapping to a small set of files with a single responsibility. Not worth further decomposition. No other Concept may have a `PartOf` edge pointing to a module. **Must have exactly one `PartOf` edge** to a parent (system, subsystem, or another module's parent).

## Repository-agnostic heuristics for kind assignment

When analysing an unfamiliar repository, follow these heuristics to determine the right `kind` for each Concept:

1. **Start with the README and package manifests.** Read `README.md`, `package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `pom.xml`, or whatever manifest the project uses. These reveal the project's stated purpose, entry points, and high-level modules.

2. **Use directory structure as the primary decomposition guide.** Top-level directories usually correspond to systems or major subsystems. Nested directories within them are candidates for subsystems or modules.

3. **Monorepo detection:** If the repository contains multiple independent packages (each with their own manifest), each package is typically a `system`. The root still represents the repository as a whole.

4. **Language-specific conventions:**
   - **Python**: `src/<pkg>/` or top-level package directories map to systems. Sub-packages map to subsystems or modules depending on depth.
   - **JavaScript/TypeScript**: `src/`, `lib/`, `packages/` directories. Each `packages/*` entry in a monorepo is often a system.
   - **Go**: Top-level `cmd/` entries are systems. `internal/` and `pkg/` subdirectories are subsystems.
   - **Rust**: Workspace members are systems. `mod.rs` boundaries guide subsystem decomposition.
   - **Java/Kotlin**: Maven/Gradle modules are systems. Package hierarchies guide further decomposition.

5. **When unsure between `subsystem` and `module`, default to `module`.** It is better to start flat and promote a module to a subsystem later (when you discover internal structure) than to create unnecessary hierarchy.

6. **Depth should match complexity.** Simple areas need 2 levels (root -> system -> module). Complex areas with distinct internal concerns may need 3-4 levels (root -> system -> subsystem -> module).

## Indexing protocol

### Step 1. Bootstrap

Run `begin_write` to start a COW session, then run `init_db` on the COW path to ensure the schema exists. This is idempotent.

### Step 2. Assess current state

Run `get_coverage` and query existing nodes to understand what has been indexed and what gaps remain. On the first run this will show an empty graph.

### Step 3. Root Concept (one per repository)

Read `README.md` and the top-level project structure. Create a single root Concept:

- `kind`: `"root"`
- `level`: `0`
- `notes`: Capture the repository's purpose, boundaries, key technologies, architectural style, and core design conventions.

There is exactly one root per indexed repository.

### Step 4. Recursive decomposition

Decompose the root into systems, then systems into subsystems and modules.

**Level derivation:** Level is not manually assigned -- it equals `parent.level + 1`. This applies to every non-root node. If a node's level does not match its PartOf parent's level + 1, the graph is inconsistent.

For each concept, read the actual code. Decompose into sub-concepts where the area has distinct internal concerns. Depth should match complexity -- simple areas need 2 levels, complex areas may need 3-4.

### Step 5. File-level intelligence

Read each source file thoroughly. The `notes` field must capture the file's **architectural role and design context**:

- What design patterns does this file implement or participate in?
- What conventions does this file establish or follow?
- What is the architectural purpose of this file within its system/subsystem?
- Non-obvious design decisions and their rationale

Create `BelongsTo` edges to the most specific concept. Create `Imports` edges for file-to-file dependencies.

### Step 6. Cross-cutting concerns

After building the local picture, identify high-level architectural interactions between systems and subsystems. Create `InteractsWith` edges to capture how major components collaborate. Create `DependsOn` edges only for **architectural-level** dependencies between systems.

### Step 7. Update state

Run `get_coverage` and report your progress.

## Quality bar for `notes` fields

The notes must pass the "useful to a new team member" test.

**Bad notes** (these add no value):

- "This file handles dispatching" -- that's the `description`, not intelligence
- "Uses asyncio" -- obvious from reading the code
- "Main entry point" -- obvious from the filename

**Good notes** (architecture, design patterns, conventions, meaning):

- "The classifier uses max_turns=1 and no tools -- this is intentional to keep classification cheap and fast. If you add tools here, every single user message will cost 10x more."
- "Worker sessions are deliberately NOT reused across messages from different users. The session ID mapping in _sessions is per chat_id. Sharing sessions across chats would leak conversation context."
- "This module follows the mediator pattern -- all inter-system communication routes through the dispatcher rather than systems calling each other directly. This keeps the dependency graph shallow and makes it possible to add new systems without modifying existing ones."
- "The project enforces a strict convention: environment variables are only read in the config module. All other modules receive configuration via constructor injection. This centralises runtime configuration and makes the system testable without env var manipulation."

## Update quality: holistic rewrites

When updating existing nodes during incremental re-indexing, the same quality standards used for initial node creation apply to every update. Specifically:

1. **No PR references.** Never mention PR numbers, commit hashes, or ticket IDs in node descriptions or notes. The graph describes the *current* state of the code, not its history.

2. **No changelog language.** Avoid phrases that describe what *changed* rather than what *is*. Banned patterns include:
   - "Previously...", "Before/After PR #X...", "Used to..."
   - "Extracted from...", "Moved from...", "Renamed to/from..."
   - "No longer...", "Now uses..." (when contrasting with a past state)
   - "Slimmed in...", "Simplified in...", "As of..."
   - "Significantly refactored...", "Was split into..."
   - "Added in...", "Introduced in..."

3. **Holistic rewrite on update.** When updating a node, do NOT append new information to existing notes or stack a new paragraph describing the delta. Instead:
   - Re-read the node's full current description and notes.
   - Re-read the current source code the node describes.
   - Rewrite the description and notes **from scratch** to produce a coherent, present-tense description of the current state.
   - The result should read as if no previous version ever existed.

4. **Describe the current state.** Write as if describing the code to a new team member who has never seen a previous version.

## Batch size and priority

- Process **10-15 files** per invocation with deep analysis. Quality over quantity.
- Priority order: root concept first (gives the architectural frame), then system decomposition, then subsystem/module depth, then file-level intelligence.

## Incremental re-indexing

When the graph is stale (HEAD differs from `git_revision` on nodes), follow this propagation protocol:

1. **Direct changes**: Re-read each changed file. Update its SourceFile node's `notes` and `description`.
2. **Neighbours**: Query the graph for files that import the changed file (`MATCH (f:SourceFile)-[:Imports]->(changed:SourceFile {path: ...}) RETURN f.path`) and files the changed file imports. Re-read neighbours and update their `notes` if the change affects their architectural role, design patterns, or conventions.
3. **Walk up the hierarchy**: For each changed file, find its parent Concept (`MATCH (f:SourceFile {path: ...})-[:BelongsTo]->(c:Concept) RETURN c.id`). Re-evaluate the Concept's `notes` -- a change in a file may shift the concept's architectural description, design patterns, or interaction model. Then check the parent's parent via `PartOf` edges and update if the change has architectural implications.
4. **Cross-cutting relationships**: Check `InteractsWith` and `DependsOn` edges involving affected Concepts. Update relationship descriptions if the architectural interaction or high-level dependency has changed.
5. **Deletions**: Remove SourceFile nodes for files that no longer exist on disk. Remove dangling relationships.

Don't wipe and rebuild -- surgically update what's affected. When writing updated descriptions and notes, follow the **Update quality: holistic rewrites** rules above.

## Structural validation before commit

Before calling `commit_write`, run all 5 integrity checks:

```bash
# 1. Missing PartOf (non-root concepts without a parent)
python -m theo.tools.query $COW_PATH "MATCH (c:Concept) WHERE c.kind <> 'root' AND NOT EXISTS { MATCH (c)-[:PartOf]->(:Concept) } RETURN c.id, c.kind"

# 2. Root with a parent (wrong)
python -m theo.tools.query $COW_PATH "MATCH (c:Concept {kind: 'root'})-[:PartOf]->(:Concept) RETURN c.id"

# 3. Level mismatch
python -m theo.tools.query $COW_PATH "MATCH (child:Concept)-[:PartOf]->(parent:Concept) WHERE child.level <> parent.level + 1 RETURN child.id, child.level, parent.id, parent.level"

# 4. Multiple parents
python -m theo.tools.query $COW_PATH "MATCH (c:Concept)-[:PartOf]->(p:Concept) WITH c, count(p) AS parents WHERE parents > 1 RETURN c.id, parents"

# 5. Cycles
python -m theo.tools.query $COW_PATH "MATCH (c:Concept)-[:PartOf*2..]->(c) RETURN c.id"
```

Fix any violations before committing.

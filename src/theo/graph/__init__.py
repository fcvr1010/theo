"""Theo graph operations -- public API.

The following modules are intentionally NOT re-exported here because they
pull in heavy dependencies (fastembed ~200 MB) that not every consumer needs:

- ``theo.graph.tool.semantic_search`` -- requires fastembed
- ``theo.graph.tool.get_coverage`` -- lightweight, but niche
- ``theo.graph.backfill_embeddings`` -- requires fastembed
- ``theo.graph.manage_indexes`` -- internal index management

Import them directly when needed, e.g.::

    from theo.graph.tool.semantic_search import semantic_search
"""

from theo.graph.init_db import init_db
from theo.graph.tool.begin_write import begin_write
from theo.graph.tool.commit_write import commit_write
from theo.graph.tool.query import query
from theo.graph.tool.upsert_node import upsert_node
from theo.graph.tool.upsert_rel import upsert_rel

__all__ = [
    "begin_write",
    "commit_write",
    "init_db",
    "query",
    "upsert_node",
    "upsert_rel",
]

"""Theo client -- read-only access to the knowledge graph.

Install with ``pip install theo[client]`` or ``pip install theo-client``.
All functions here are read-only. They never modify the graph.

Usage::

    from theo.client import query, semantic_search, get_coverage
"""

from theo.client.get_coverage import get_coverage
from theo.client.query import query

__all__ = [
    "get_coverage",
    "query",
    "semantic_search",
]


def __getattr__(name: str):
    """Lazy-import semantic_search to avoid loading fastembed at import time."""
    if name == "semantic_search":
        from theo.client.semantic_search import semantic_search

        return semantic_search
    raise AttributeError(f"module 'theo.client' has no attribute {name!r}")

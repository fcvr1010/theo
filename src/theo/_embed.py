"""Semantic embeddings using fastembed + nomic-embed-text-v1.5."""

from __future__ import annotations

import logging
from typing import Any

from theo._schema import EMBEDDING_DIM

_log = logging.getLogger(__name__)

# Re-export for modules that reach EMBEDDING_DIM via ``theo._embed``.
__all__ = [
    "EMBEDDING_DIM",
    "MODEL_NAME",
    "embed_documents",
    "embed_query",
    "make_edge_text",
    "make_node_text",
    "prewarm_model",
    "reset_model",
]

# Canonical model name.  Changing it (or EMBEDDING_DIM in ``_schema``) requires
# re-running ``theo reindex`` so all stored embeddings match.
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"

# Nomic's embed-text models require task-specific prefixes prepended to the
# input for the vectors to land in the right region of the space.
_DOC_PREFIX = "search_document"
_QUERY_PREFIX = "search_query"

# Singleton: the model is expensive to load (~2 s cold start) but stateless,
# so we keep one instance alive for the process lifetime.
_model: Any = None


def _get_model() -> Any:
    """Lazy-load the embedding model on first use."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _log.info("Loading embedding model %s (first call)", MODEL_NAME)
        _model = TextEmbedding(MODEL_NAME)
    return _model


def prewarm_model() -> None:
    """Force the embedding model to load now.

    Intended for server startup: callers that do not want to pay the ~2 s
    cold-start cost on the first user-facing operation can invoke this
    during initialisation.  Propagates any load error so callers can decide
    whether to log-and-continue or abort.
    """
    _get_model()


def reset_model() -> None:
    """Release the singleton model (tests / memory hygiene)."""
    global _model
    _model = None


def make_node_text(description: str | None, notes: str | None) -> str:
    """Build the string embedded for a node: ``description \\n\\n notes``.

    Empty components are dropped; returns ``""`` if both are blank so the
    caller can skip embedding.
    """
    parts = [p for p in (description, notes) if p]
    return "\n\n".join(parts)


def make_edge_text(description: str | None) -> str:
    """Build the string embedded for a relationship (``description`` only)."""
    return description or ""


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a batch of documents (for indexing).

    Applies the ``search_document:`` prefix automatically.  Returns plain
    Python lists so the vectors are JSON-friendly and Cypher-bindable.
    """
    if not texts:
        return []
    model = _get_model()
    prefixed = [f"{_DOC_PREFIX}: {t}" for t in texts]
    return [list(vec) for vec in model.embed(prefixed)]


def embed_query(query: str) -> list[float]:
    """Embed a single query with the ``search_query:`` prefix."""
    model = _get_model()
    vec = next(iter(model.embed([f"{_QUERY_PREFIX}: {query}"])))
    return list(vec)

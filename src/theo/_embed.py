"""Semantic embeddings using fastembed + nomic-embed-text-v1.5.

``fastembed`` is an optional dependency (``theo[semantic]`` extra).  The
module imports it lazily so that callers with the extra uninstalled can
still import ``theo._embed`` and probe for availability.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# Canonical model name and output dimension.  Changing either requires
# re-running ``theo reindex`` so all stored embeddings match.
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIM = 768

# Nomic's embed-text models require task-specific prefixes prepended to the
# input for the vectors to land in the right region of the space.
_DOC_PREFIX = "search_document"
_QUERY_PREFIX = "search_query"

_INSTALL_HINT = "fastembed is not installed. Install with: pip install 'theo[semantic]'."

# Singleton: the model is expensive to load (~2 s cold start) but stateless,
# so we keep one instance alive for the process lifetime.
_model: Any = None


def is_available() -> bool:
    """Return True iff ``fastembed`` can be imported."""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def _get_model() -> Any:
    """Lazy-load the embedding model.

    Raises ``RuntimeError`` with an install hint if ``fastembed`` is missing.
    Return type is ``Any`` because ``fastembed.TextEmbedding`` is only
    available when the optional extra is installed.
    """
    global _model
    if _model is None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(_INSTALL_HINT) from exc
        _log.info("Loading embedding model %s (first call)", MODEL_NAME)
        _model = TextEmbedding(MODEL_NAME)
    return _model


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

    Loads the model unconditionally so callers with no inputs still surface
    a missing-fastembed install hint instead of silently succeeding.
    """
    model = _get_model()
    if not texts:
        return []
    prefixed = [f"{_DOC_PREFIX}: {t}" for t in texts]
    return [list(vec) for vec in model.embed(prefixed)]


def embed_query(query: str) -> list[float]:
    """Embed a single query with the ``search_query:`` prefix."""
    model = _get_model()
    vec = next(iter(model.embed([f"{_QUERY_PREFIX}: {query}"])))
    return list(vec)

"""
Embed text for semantic search.

    embed_text(texts, prefix="search_document") -> list[list[float]]
    embed_query(query) -> list[float]

Uses fastembed with the model specified in TheoConfig.embedding_model
(default: nomic-embed-text-v1.5, 768-dim vectors).
prefix: "search_document" for indexing, "search_query" for querying.
The nomic model requires explicit prefix strings prepended to the text.
"""

from __future__ import annotations

import threading

from fastembed import TextEmbedding

from theo import get_logger
from theo.config import TheoConfig

_log = get_logger("embed_text")

# Canonical model name -- sourced from TheoConfig so it can be overridden
# via the THEO_EMBEDDING_MODEL environment variable.
MODEL_NAME: str = TheoConfig().embedding_model

# Singleton: the embedding model is expensive to load (~2 s cold start) and
# stateless, so we keep a single instance alive for the process lifetime.
# Thread-safe via double-checked locking (same pattern as theo.__init__).
_model: TextEmbedding | None = None
_model_lock = threading.Lock()


def _get_model() -> TextEmbedding:
    """Lazy-load the embedding model (thread-safe singleton)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = TextEmbedding(MODEL_NAME)
    return _model


def reset_model() -> None:
    """Release the singleton model instance to free memory."""
    global _model
    with _model_lock:
        _model = None


def embed_text(texts: list[str], prefix: str = "search_document") -> list[list[float]]:
    """Embed a batch of texts for indexing or search.

    Args:
        texts: The texts to embed.
        prefix: Nomic task prefix -- "search_document" for indexing,
                "search_query" for querying, "classification", or "clustering".

    Returns:
        List of embedding vectors (plain Python lists for JSON compatibility).
    """
    if not texts:
        return []
    _log.info("[EMBED] Embedding %d texts (prefix=%s)", len(texts), prefix)
    model = _get_model()
    prefixed = [f"{prefix}: {t}" for t in texts]
    embeddings = model.embed(prefixed)
    return [vec.tolist() for vec in embeddings]


def embed_query(query: str) -> list[float]:
    """Embed a single query for semantic search.

    Applies the "search_query" prefix automatically.

    Args:
        query: The search query text.

    Returns:
        A single embedding vector (plain Python list).
    """
    return embed_text([query], prefix="search_query")[0]


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m theo._embed <text> [prefix]", file=sys.stderr)
        sys.exit(1)

    text = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else "search_document"
    result = embed_text([text], prefix=prefix)
    print(json.dumps({"dim": len(result[0]), "embedding": result[0][:5]}, indent=2))

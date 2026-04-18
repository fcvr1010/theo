"""KuzuDB extension helpers.

Centralises the INSTALL / LOAD dance for extensions that Theo needs (today:
``VECTOR`` for HNSW vector indexes and ``array_cosine_similarity``).
"""

from __future__ import annotations

import contextlib

import real_ladybug as lb


def load_vector_ext(conn: lb.Connection) -> None:
    """Install (once, best-effort) and load the VECTOR extension.

    ``INSTALL`` is a no-op on a second invocation but raises if the binary
    has already been linked; we swallow that specific failure.  ``LOAD`` is
    required per connection.
    """
    with contextlib.suppress(RuntimeError):
        conn.execute("INSTALL VECTOR")
    conn.execute("LOAD EXTENSION VECTOR")

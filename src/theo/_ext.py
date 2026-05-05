"""KuzuDB extension helpers.

Centralises the INSTALL / LOAD dance for extensions that Theo needs (today:
``VECTOR`` for HNSW vector indexes and ``array_cosine_similarity``).
"""

from __future__ import annotations

import real_ladybug as lb

# Sentinel substrings used to detect the benign "extension binary already
# present" / "already linked" state when re-running ``INSTALL VECTOR`` on a
# DB that has previously had it installed.  Coupled to the pinned ladybug
# version (see ``pyproject.toml`` -- currently ``real-ladybug==0.15.3``,
# where ``INSTALL`` is fully idempotent and emits no error; the sentinels
# below cover wording observed on older ladybug builds and act as a defence
# in depth so any future regression surfaces as a benign no-op rather than
# a hard failure).  If a ladybug upgrade changes the wording, the sentinel
# stops matching and a real failure here will surface as a clear ``INSTALL
# VECTOR`` RuntimeError instead of a cryptic downstream ``LOAD EXTENSION``
# error -- which is the desired loud-fail behaviour.
_ERR_EXT_INSTALLED = ("already linked", "already installed")


def load_vector_ext(conn: lb.Connection) -> None:
    """Install (once, best-effort) and load the VECTOR extension.

    ``INSTALL`` is intended to be a no-op on a second invocation but on
    older ladybug builds it has been observed to raise ``RuntimeError`` with
    wording like "binary already linked".  We swallow only that specific
    benign signal and re-raise every other RuntimeError so genuine install
    failures (network, permissions, version incompatibility) surface here
    rather than producing a cryptic downstream ``LOAD EXTENSION`` error.

    ``LOAD`` is required per connection.
    """
    try:
        conn.execute("INSTALL VECTOR")
    except RuntimeError as exc:
        if not any(s in str(exc) for s in _ERR_EXT_INSTALLED):
            raise
    conn.execute("LOAD EXTENSION VECTOR")

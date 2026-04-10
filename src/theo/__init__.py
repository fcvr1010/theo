"""Theo -- codebase intelligence agent."""

from __future__ import annotations

__version__ = "0.1.0-dev"

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_lock = threading.Lock()
_handler_installed = False


def _log_dir() -> Path | None:
    """Return the directory for Theo log files, or *None* to skip file logging.

    Uses the ``THEO_LOG_DIR`` environment variable when set; otherwise returns
    *None* so that installing Theo never silently creates ``~/.theo/`` on the
    user's machine.
    """
    env = os.environ.get("THEO_LOG_DIR")
    if env:
        return Path(env)
    return None


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to the shared Theo operations log file.

    Safe to call multiple times from any thread -- the file handler is
    installed once using double-checked locking.  When no ``THEO_LOG_DIR``
    is configured, no file handler is installed and the logger inherits
    Python's default NullHandler behaviour.
    """
    global _handler_installed

    logger = logging.getLogger(f"theo.{name}")

    if not _handler_installed:
        with _lock:
            if not _handler_installed:
                log_path_dir = _log_dir()
                if log_path_dir is not None:
                    log_path = log_path_dir / "theo-ops.log"
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
                    handler.setFormatter(
                        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
                    )
                    # Attach to the parent "theo" logger so all children inherit it.
                    parent = logging.getLogger("theo")
                    level_name = os.environ.get("THEO_LOG_LEVEL", "INFO").upper()
                    parent.setLevel(getattr(logging, level_name, logging.INFO))
                    parent.propagate = False
                    parent.addHandler(handler)
                    _handler_installed = True

    return logger

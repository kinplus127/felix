"""File logging for the backend and mpv. No playback logic."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from felix.config import CONFIG_DIR, LOG_PATH

_configured = False


def setup_logging() -> Path:
    """Idempotent. Writes rotating logs to ~/.config/felix/felix.log."""
    global _configured
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _configured:
        return LOG_PATH

    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger("felix")
    root.setLevel(logging.INFO)
    if not root.handlers:
        root.addHandler(handler)
    if LOG_PATH.exists():
        os.chmod(LOG_PATH, 0o600)
    _configured = True
    root.info("logging started path=%s", LOG_PATH)
    return LOG_PATH


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"felix.{name}" if not name.startswith("felix") else name)

"""Logging configuration.

Logs go to a rotating file in the user profile so support can collect them
without needing Fusion's text command window. Secrets (tokens, client
secrets) must never be passed to the logger.
"""

import logging
import logging.handlers
import os

from .constants import ADDIN_NAME

_CONFIGURED = False

DEBUG_ENV = "MFGTOFM_DEBUG"
DEBUG_FLAG_FILE = "debug.flag"   # an empty file of this name in the log directory switches verbose logging on


def log_directory() -> str:
    """Return (and create) the per-user log directory."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/Library/Logs")
    path = os.path.join(base, ADDIN_NAME, "logs")
    os.makedirs(path, exist_ok=True)
    return path


def verbose() -> bool:
    """True when verbose (development) logging is on: ``MFGTOFM_DEBUG=1``, or a ``debug.flag`` file in the log directory.

    Verbose logs carry full request and response bodies, so they may hold business data: never share them unreviewed.
    Read when the add-in starts; restart it after changing the flag.
    """
    if os.environ.get(DEBUG_ENV, "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return os.path.exists(os.path.join(log_directory(), DEBUG_FLAG_FILE))


def get_logger(name: str = ADDIN_NAME) -> logging.Logger:
    """Return a logger, configuring the file handler on first use."""
    global _CONFIGURED
    root = logging.getLogger(ADDIN_NAME)
    if not _CONFIGURED:
        root.setLevel(logging.DEBUG if verbose() else logging.INFO)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_directory(), f"{ADDIN_NAME}.log"),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        _CONFIGURED = True
        if root.level == logging.DEBUG:
            root.debug("Verbose logging is on")
    return root if name == ADDIN_NAME else root.getChild(name)


def shutdown_logging() -> None:
    """Close handlers so the log file is released when the add-in stops."""
    global _CONFIGURED
    root = logging.getLogger(ADDIN_NAME)
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    _CONFIGURED = False

"""The summary of a design, kept on disk per design version.

A summary (the component id, composition, item number, part number and description of the design) is read from the
Data Model, which takes about two seconds. The key names a version of the design (its model id and the timestamp that
pins it), and a version does not change, so the same answer is kept and a design opened again needs no read.
"""

import json
import os
import tempfile
import threading
from typing import Any, Dict, Optional

from ..core.constants import ADDIN_NAME
from ..core.logging_setup import get_logger

log = get_logger("summary_cache")

MAX_ENTRIES = 200   # the least recently used go first


def cache_path() -> str:
    """Per-user cache file, next to the configuration."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/Library/Application Support")
    folder = os.path.join(base, ADDIN_NAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "summary-cache.json")


class SummaryCache:
    """Summaries by design version key. Safe to use from several threads."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or cache_path()
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict[str, Any]] = self._read()   # oldest use first

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """The summary kept for ``key``, or None."""
        with self._lock:
            summary = self._entries.get(key)
            if summary is None:
                return None
            self._entries[key] = self._entries.pop(key)   # now the most recently used
            return dict(summary)

    def put(self, key: str, summary: Dict[str, Any]) -> None:
        """Keep ``summary`` for ``key`` (replacing an older one)."""
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = dict(summary)
            while len(self._entries) > MAX_ENTRIES:
                del self._entries[next(iter(self._entries))]
            self._write()

    def _read(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:   # a cache is only a copy: unreadable, it starts again
            log.warning("The summary cache could not be read (%s); starting it again", exc)
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}

    def _write(self) -> None:
        """Replace the file in one step, so a crash never leaves half of it."""
        folder = os.path.dirname(self._path)
        try:
            handle, temp = tempfile.mkstemp(dir=folder, suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(self._entries, out)
            os.replace(temp, self._path)
        except OSError as exc:   # not being able to keep a copy costs only the next read
            log.warning("The summary cache could not be written: %s", exc)

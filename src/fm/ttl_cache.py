"""A small cache whose entries expire, for what a workspace's layout rarely changes."""

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

CACHE_SECONDS = 300   # runs queued close together share one read
SWEEP_AT = 256   # entries a cache holds before a ``put`` drops the expired ones, so keys that are never asked for again do not pile up


class TtlCache:
    """Values by key, each good for ``seconds`` after it was kept. Any thread may use it.

    A value is never None: None is what ``get`` answers for a key that has nothing kept, so there is no telling a kept None from none.
    ``clock`` tells the time in seconds (the monotonic clock when not given; a test gives its own).
    """

    def __init__(self, seconds: float = CACHE_SECONDS, clock: Optional[Callable[[], float]] = None) -> None:
        self._seconds, self._clock = seconds, clock
        self._lock = threading.Lock()
        self._entries: Dict[Any, Tuple[float, Any]] = {}   # key -> (when it was kept, value)

    def get(self, key: Any) -> Optional[Any]:
        """The value kept for ``key``, or None when there is none or it has expired."""
        with self._lock:
            kept = self._entries.get(key)
            if kept is None:
                return None
            if self._expired(kept[0]):
                del self._entries[key]
                return None
            return kept[1]

    def put(self, key: Any, value: Any) -> Any:
        """Keep ``value`` for ``key``; returns it."""
        with self._lock:
            if len(self._entries) >= SWEEP_AT:
                self._entries = {k: kept for k, kept in self._entries.items() if not self._expired(kept[0])}
            self._entries[key] = (self._now(), value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _now(self) -> float:
        return self._clock() if self._clock else time.monotonic()

    def _expired(self, kept_at: float) -> bool:
        return self._now() - kept_at >= self._seconds

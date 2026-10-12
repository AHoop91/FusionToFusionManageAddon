"""A small cache whose entries expire, for what a workspace's layout rarely changes."""

import time
from typing import Any, Dict, Optional, Tuple

CACHE_SECONDS = 300   # runs queued close together share one read


class TtlCache:
    """Values by key, each good for ``seconds`` after it was kept."""

    def __init__(self, seconds: float = CACHE_SECONDS) -> None:
        self._seconds = seconds
        self._entries: Dict[Any, Tuple[float, Any]] = {}

    def get(self, key: Any) -> Optional[Any]:
        """The value kept for ``key``, or None when there is none or it has expired."""
        kept = self._entries.get(key)
        if kept and time.monotonic() - kept[0] < self._seconds:
            return kept[1]
        return None

    def put(self, key: Any, value: Any) -> Any:
        """Keep ``value`` for ``key``; returns it."""
        self._entries[key] = (time.monotonic(), value)
        return value

    def clear(self) -> None:
        self._entries.clear()

"""Reads of a saved version of a design that are asked for repeatedly, cached while that version is the one in use.

A saved version of a design never changes, so what the Data Model said about it (its summary, bill of materials and properties) is still
true the next time it is asked. Only the most recent version asked about is held: the design in use.

Callers must not modify what they are given. Reads of one version are serialised, so a burst of callers (the item number of a selection,
the up-to-date check of a tab) triggers each read once.
"""

import threading
from typing import Any, Callable, Dict, Tuple

from .fusion_graphql_client import FusionGraphQlClient
from .model_service import read_section


class DesignReads:
    """Cache of the Data Model reads for the design version in use. Safe to call from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._version: Tuple[str, str] = ("", "")   # (model id, saved-at time) of the version held
        self._values: Dict[str, Any] = {}

    def _get(self, model_id: str, saved_at: str, name: str, read: Callable[[], Any]) -> Any:
        """The cached value called ``name`` for the version, reading it first if needed; asking for another version drops the cache.
        The lock is held during the read, so concurrent callers wait for it instead of repeating it. A read that raises is not cached."""
        with self._lock:
            if self._version != (model_id, saved_at):
                self._version, self._values = (model_id, saved_at), {}
            if name not in self._values:
                self._values[name] = read()
            return self._values[name]

    def summary(self, client: FusionGraphQlClient, model_id: str, saved_at: str) -> Dict[str, Any]:
        """The summary of the version (``read_section`` "summary")."""
        return self._get(model_id, saved_at, "summary", lambda: read_section(client, "summary", model_id, saved_at))

    def structure(self, client: FusionGraphQlClient, model_id: str, saved_at: str, summary: Dict[str, Any]) -> Any:
        """The bill of materials of the version, flat in tree order (``read_section`` "structure")."""
        return self._get(model_id, saved_at, "structure", lambda: read_section(client, "structure", model_id, saved_at, summary))

    def properties(self, client: FusionGraphQlClient, model_id: str, saved_at: str, summary: Dict[str, Any], physical: bool) -> Any:
        """The properties of the design's own component, with its physical properties when ``physical`` (cached separately from without)."""
        return self._get(model_id, saved_at, f"properties:{physical}",
                         lambda: read_section(client, "properties", model_id, saved_at, summary, "", physical))

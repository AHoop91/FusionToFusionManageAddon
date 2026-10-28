"""Reads of a saved version of a design that are asked for again and again, kept while that version is the one in use.

A saved version of a design never changes, so what the Data Model said of it (its summary, its bill of materials, its properties) is
still true the next time it is asked. Only the latest version asked about is held: the design in use. Callers must not change what they
are given. The reads of one version are made one at a time, so a burst of callers (the item number of a selection, the up-to-date check
of a tab) reads each once.
"""

import threading
from typing import Any, Callable, Dict, Tuple

from .fusion_graphql_client import FusionGraphQlClient
from .model_service import read_section


class DesignReads:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: Tuple[str, str] = ("", "")   # (model id, time) of the version held
        self._values: Dict[str, Any] = {}

    def _get(self, model_id: str, time: str, name: str, read: Callable[[], Any]) -> Any:
        with self._lock:
            if self._key != (model_id, time):
                self._key, self._values = (model_id, time), {}
            if name not in self._values:   # a read that fails is not kept
                self._values[name] = read()
            return self._values[name]

    def summary(self, client: FusionGraphQlClient, model_id: str, time: str) -> Dict[str, Any]:
        return self._get(model_id, time, "summary", lambda: read_section(client, "summary", model_id, time))

    def structure(self, client: FusionGraphQlClient, model_id: str, time: str, summary: Dict[str, Any]) -> Any:
        """The bill of materials of the version, flat in tree order (``read_section`` "structure")."""
        return self._get(model_id, time, "structure", lambda: read_section(client, "structure", model_id, time, summary))

    def properties(self, client: FusionGraphQlClient, model_id: str, time: str, summary: Dict[str, Any], physical: bool) -> Any:
        """The properties of the design's own component, with its physical properties when ``physical``."""
        return self._get(model_id, time, f"properties:{physical}",
                         lambda: read_section(client, "properties", model_id, time, summary, "", physical))

"""The reads of a publish run that are shared between its items, started before the items need them.

Asking the Data Model and Fusion Manage about each item on its own costs two or three requests per item. Here the items' components
go to the Data Model several to a request, and their item numbers go to Fusion Manage several to a search that returns the item
details too. The requests start as the run starts and each item takes its answer when it gets to it; an item whose answer did not
come (a search that found nothing) falls back to asking for itself. A search that fails raises, for the run to stop.
"""

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from ..core.logging_setup import get_logger
from ..fm.client import FmClient
from ..fm.items import ItemService
from ..fm.search_query import WORKING
from ..fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ..fusion_mfg.model_service import publish_batch_size, read_publish_components
from ..sync.item_compare import item_number_of

log = get_logger("publish")

DATA_MODEL_REQUESTS = 3   # Data Model requests in flight, each holding several components (the services limit how many requests there may be)
SEARCHES = 2              # Fusion Manage searches in flight
SEARCH_NUMBERS = 10       # item numbers to one search


def component_id_of(item: Dict[str, Any], summary: Dict[str, Any]) -> str:
    """The Data Model id of the component an item of the job stands for (the design's own for the root item)."""
    return str(summary.get("component_id") or "") if item.get("root") else str(item.get("id") or "")


def _chunks(values: List[str], size: int) -> List[List[str]]:
    return [values[start:start + size] for start in range(0, len(values), size)]


class ReadAhead:
    """Starts the shared reads of a run on entering, and waits for them to finish on leaving."""

    def __init__(self, items: List[Dict[str, Any]], summary: Dict[str, Any], client: FusionGraphQlClient, fm: FmClient, workspace_id: str,
                 model_time: str, physical: bool, cancelled: Callable[[], bool]) -> None:
        self._items, self._summary, self._client, self._fm = items, summary, client, fm
        self._workspace_id, self._time, self._physical, self._cancelled = workspace_id, model_time, physical, cancelled
        self._reads: Dict[str, "Future[Dict[str, Any]]"] = {}   # component id -> the request that reads it, shared with the components beside it
        self._searches: Dict[str, "Future[Dict[str, List[Dict[str, Any]]]]"] = {}   # item number -> the search that looks for it, shared likewise
        self._pools: List[ThreadPoolExecutor] = []
        self._count_lock = threading.Lock()
        self.to_search = 0   # item numbers the shared search looks for, for a progress bar
        self.searched = 0    # of those, how many have been looked for
        self._hits: Dict[str, int] = {}   # item number -> how many Fusion Manage items carry it, for the numbers looked for so far

    def __enter__(self) -> "ReadAhead":
        numbered = [item for item in self._items if item_number_of(item)]
        ids = [cid for cid in (component_id_of(item, self._summary) for item in numbered) if cid]
        self._start(self._reads, ids, publish_batch_size(self._physical), DATA_MODEL_REQUESTS, self._read_chunk)
        if self._workspace_id:
            numbers = sorted({item_number_of(item) for item in numbered})
            self.to_search = len(numbers)
            self._start(self._searches, numbers, SEARCH_NUMBERS, SEARCHES, self._search_chunk)
        return self

    def __exit__(self, failed: Any, *_: Any) -> None:
        """Wait for the reads to finish; when the run is stopping, drop those not started instead, so it does not wait for reads it will not use."""
        for pool in self._pools:
            pool.shutdown(wait=not failed, cancel_futures=bool(failed))

    def _start(self, futures: Dict[str, Future], keys: List[str], size: int, workers: int, read: Callable[[List[str]], Any]) -> None:
        pool = ThreadPoolExecutor(max_workers=workers)
        self._pools.append(pool)
        for chunk in _chunks(keys, size):
            future = pool.submit(read, chunk)
            futures.update({key: future for key in chunk})

    def _read_chunk(self, ids: List[str]) -> Dict[str, Any]:
        return {} if self._cancelled() else read_publish_components(self._client, self._summary, ids, self._time, self._physical)

    def _search_chunk(self, numbers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """The hits of each number the search found. A failed search raises: the run needs every number looked for before it writes."""
        if self._cancelled():
            return {}
        found = ItemService(self._fm, WORKING).find_many(self._workspace_id, numbers)
        with self._count_lock:
            self.searched += len(numbers)
            self._hits.update({number: len(found.get(number.strip().lower()) or []) for number in numbers})
        return found

    def hits(self) -> Dict[str, int]:
        """How many items carry each item number the search has answered for."""
        with self._count_lock:
            return dict(self._hits)

    def read(self, component_id: str) -> Dict[str, Any]:
        """What the Data Model gave for the component (see ``read_publish_components``); raises what kept it from being read."""
        future = self._reads.get(component_id)
        if future is None:
            raise ValueError("The summary has no component id yet.")
        found = future.result().get(component_id)
        if found is None:
            raise RuntimeError("Cancelled.")
        if isinstance(found, Exception):
            raise found
        return found

    def found(self, number: str) -> Optional[List[Dict[str, Any]]]:
        """The hits the shared search found for the item number, or None for the item to look for itself."""
        future = self._searches.get(number)
        return future.result().get(number.strip().lower()) if future else None

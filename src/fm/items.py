"""Search for and read Fusion Manage items.

Used to show what already exists in Fusion Manage next to the Manufacturing
Data Model values. Items are found by item number through the search API, then their fields
are read back.

The item JSON is walked generically for ``.../fields/<FIELD_ID>`` entries, so
the reader does not depend on how a workspace groups its fields into sections.
"""

import re
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmClient

log = get_logger("fm.items")

SEARCH_LIMIT = 50      # most items listed for one item number
FIND_PAGE = 50         # items one page of a search that carries the item details holds
ITEMS_BULK = "application/vnd.autodesk.plm.items.bulk+json"   # asked of a search: each hit is the item with its fields, not only a link
FIELD_ID = re.compile(r"/fields/([^/]+)/?$")
_ITEM_ID = re.compile(r"/items/(\d+)")


def display_text(value: Any) -> str:
    """Field value as the text a user sees."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("title") or value.get("value") or value.get("name") or "")
    if isinstance(value, list):
        return ", ".join(t for t in (display_text(v) for v in value) if t)
    return str(value)


def collect_values(node: Any, found: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every ``field id -> value as Fusion Manage holds it`` (a picklist is ``{"link", "title"}``) found in an item's JSON."""
    found = {} if found is None else found
    if isinstance(node, dict):
        match = FIELD_ID.search(str(node.get("__self__", "")))
        if match and "value" in node:
            found[match.group(1)] = node["value"]
        for child in node.values():
            collect_values(child, found)
    elif isinstance(node, list):
        for child in node:
            collect_values(child, found)
    return found


def display_values(values: Dict[str, Any]) -> Dict[str, str]:
    """``field id -> display text`` for values read with ``collect_values``."""
    return {field: display_text(value) for field, value in values.items()}


def _rows(data: Any) -> List[Dict[str, Any]]:
    """The items of a search-results answer."""
    rows = data.get("items") if isinstance(data, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _item_id(row: Dict[str, Any]) -> str:
    """The id of the item a search row names ("" if none): the number after ``/items/`` in its link."""
    for key in ("__self__", "link", "urn"):
        match = _ITEM_ID.search(str(row.get(key, "")))
        if match:
            return match.group(1)
    return ""


def _hits(data: Any) -> List[Dict[str, str]]:
    """``{"id", "descriptor"}`` for each item of a search-results answer."""
    return [{"id": item_id, "descriptor": str(row.get("descriptor") or item_id)} for row in _rows(data) if (item_id := _item_id(row))]


def number_of(descriptor: str) -> str:
    """The item number of an item descriptor (``9410-306 - STEP`` is ``9410-306``), as it is compared: trimmed, in lower case."""
    return descriptor.split(" - ", 1)[0].strip().lower()


def pick_hit(hits: List[Dict[str, str]], number: str) -> Dict[str, str]:
    """The hit whose descriptor starts with exactly ``number`` (``9410-306 - STEP``), else the first; ``hits`` must not be empty."""
    wanted = number.strip().lower()
    for hit in hits:
        if number_of(hit["descriptor"]) == wanted:
            return hit
    return hits[0]


def resolve_hits(hits: List[Dict[str, str]], number: str, chosen: str = "") -> Tuple[Optional[Dict[str, str]], List[Dict[str, str]]]:
    """``(hit, competing)`` for the ``hits`` of a search for ``number``: the item to use, or None when the user has to choose.

    ``competing`` are the items that share the number: those whose descriptor starts with exactly ``number``, else every hit. Exactly one
    of them is used as it is. Several are a choice for the user: ``chosen`` (an item id picked earlier) settles it when it is one of them,
    else the hit is None. ``competing`` is empty when there are no hits.
    """
    wanted = number.strip().lower()
    exact = [hit for hit in hits if number_of(hit["descriptor"]) == wanted]
    competing = exact or list(hits)
    picked = next((hit for hit in competing if hit["id"] == chosen), None) if chosen else None
    if picked is None and len(competing) == 1:
        picked = competing[0]
    return picked, competing


class ItemChoices:
    """The item the user picked where several items share an item number, by workspace and number, for as long as the add-in runs.

    One store is shared by the Item panel and by the uploads that start from it, so they cannot disagree. Any thread may use it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chosen: Dict[Tuple[str, str], str] = {}

    @staticmethod
    def _key(workspace_id: str, number: str) -> Tuple[str, str]:
        return workspace_id, number.strip().lower()

    def set(self, workspace_id: str, number: str, item_id: str) -> None:
        """Remember ``item_id`` for the number; an empty id forgets the choice."""
        with self._lock:
            if item_id:
                self._chosen[self._key(workspace_id, number)] = item_id
            else:
                self._chosen.pop(self._key(workspace_id, number), None)

    def resolve(self, workspace_id: str, number: str, hits: List[Dict[str, str]]) -> Tuple[Optional[Dict[str, str]], List[Dict[str, str]]]:
        """``resolve_hits`` with the choice made for the number. A choice that is none of the hits any more is forgotten."""
        with self._lock:
            chosen = self._chosen.get(self._key(workspace_id, number), "")
            if chosen and not any(hit["id"] == chosen for hit in hits):
                self._chosen.pop(self._key(workspace_id, number), None)
                chosen = ""
        return resolve_hits(hits, number, chosen)


class ItemService:
    """Finds and reads items of a workspace through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def search(self, workspace_id: str, item_number: str) -> List[Dict[str, str]]:
        """Items of the workspace whose descriptor matches ``item_number``, as ``{"id", "descriptor"}``."""
        if not item_number:
            return []
        query = quote_plus(f'itemDescriptor="{item_number}" AND (workspaceId={workspace_id})', safe="()")
        data = self._client.get_json(
            f"/api/v3/search-results?limit={SEARCH_LIMIT}&offset=0&page=1&query={query}&revision=1")
        hits = _hits(data)
        log.info("Item number %s matched %d item(s) in workspace %s", item_number, len(hits), workspace_id)
        return hits

    def read(self, workspace_id: str, item_id: str) -> Dict[str, Any]:
        """The item's fields as ``{field id: value}``, picklists as Fusion Manage holds them (``display_values`` gives the text)."""
        return collect_values(self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}"))

    def find_many(self, workspace_id: str, numbers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """The items of the workspace whose item number is one of ``numbers``, in one search that returns the item details too.

        By item number (trimmed, lower case), each with its hits as ``{"id", "descriptor", "values"}`` (``values`` as ``read`` gives them,
        empty when the answer carried no fields). A number the answer holds no hit for is left out: that is not "no such item", since
        this search may differ from the one by number alone, so the caller asks for it again on its own. Raises ``FmApiError`` when it fails."""
        numbers = [n for n in numbers if n.strip()]
        wanted = {n.strip().lower() for n in numbers}
        if not wanted:
            return {}
        terms = " OR ".join(f'itemDescriptor="{n}"' for n in numbers)
        query = quote_plus(f"({terms}) AND (workspaceId={workspace_id})", safe="()")
        found: Dict[str, List[Dict[str, Any]]] = {}
        offset = 0
        while True:
            data = self._client.get_json(
                f"/api/v3/search-results?limit={FIND_PAGE}&offset={offset}&page={offset // FIND_PAGE + 1}&query={query}&revision=1",
                accept=ITEMS_BULK)
            rows = _rows(data)
            for row in rows:
                descriptor = str(row.get("descriptor") or row.get("itemDescriptor") or row.get("title") or "")
                item_id = _item_id(row)
                if item_id and number_of(descriptor) in wanted:
                    found.setdefault(number_of(descriptor), []).append({"id": item_id, "descriptor": descriptor, "values": collect_values(row)})
            offset += FIND_PAGE
            if not rows or offset >= int(data.get("totalCount") or 0):
                break
        log.info("Searched %d item number(s) in workspace %s: %d found", len(wanted), workspace_id, len(found))
        return found

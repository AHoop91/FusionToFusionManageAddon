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

from ..core.logging_setup import get_logger
from ..core.shapes import dict_rows, dig, whole
from .client import WORKSPACES, FmClient
from .pages import FIELD_ID, LINK_KEYS
from .search_query import WORKING, encode

log = get_logger("fm.items")

SEARCH_RESULTS = "/api/v3/search-results"
SEARCH_LIMIT = 50      # most items listed for one item number
FIND_PAGE = 50         # items one page of a search that carries the item details holds
ITEMS_BULK = "application/vnd.autodesk.plm.items.bulk+json"   # asked of a search: each hit is the item with its fields, not only a link
DESCRIPTOR_KEYS = ("descriptor", "itemDescriptor", "title")   # and its descriptor
_ITEM_ID = re.compile(r"/items/(\d+)")

Hit = Dict[str, str]   # an item a search found: ``{"id", "descriptor"}`` (the panel takes it as it is, so it is a plain object)


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
        match = FIELD_ID.search(str(node.get("__self__") or ""))
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
    return dict_rows(dig(data, "items"))


def item_id_of(row: Dict[str, Any]) -> str:
    """The id of the item a search row names ("" if none): the number after ``/items/`` in its link."""
    for key in LINK_KEYS:
        match = _ITEM_ID.search(str(row.get(key) or ""))
        if match:
            return match.group(1)
    return ""


def _hits(data: Any) -> List[Hit]:
    """``{"id", "descriptor"}`` for each item of a search-results answer."""
    return [{"id": item_id, "descriptor": str(row.get("descriptor") or item_id)} for row in _rows(data) if (item_id := item_id_of(row))]


def number_key(descriptor: str) -> str:
    """The item number of an item descriptor (``9410-306 - STEP`` is ``9410-306``), as it is compared: trimmed, in lower case."""
    return descriptor.split(" - ", 1)[0].strip().lower()


def _quoted(number: str) -> str:
    """``number`` as a quoted search term. A quote or backslash would end the term early, so they are left out."""
    return '"' + number.strip().replace('"', "").replace("\\", "") + '"'


def _page_path(query: str, offset: int, limit: int, revision: int) -> str:
    """The request path of one page of a search for ``query`` (not yet encoded)."""
    return f"{SEARCH_RESULTS}?limit={limit}&offset={offset}&page={offset // limit + 1}&query={encode(query)}&revision={revision}"


def resolve_hits(hits: List[Hit], number: str, chosen: str = "") -> Tuple[Optional[Hit], List[Hit]]:
    """``(hit, competing)`` for the ``hits`` of a search for ``number``: the item to use, or None when the user has to choose.

    ``competing`` are the items that share the number: those whose descriptor starts with exactly ``number``, else every hit. Exactly one
    of them is used as it is. Several are a choice for the user: ``chosen`` (an item id picked earlier) settles it when it is one of them,
    else the hit is None. ``competing`` is empty when there are no hits.
    """
    wanted = number.strip().lower()
    exact = [hit for hit in hits if number_key(hit["descriptor"]) == wanted]
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

    def resolve(self, workspace_id: str, number: str, hits: List[Hit]) -> Tuple[Optional[Hit], List[Hit]]:
        """``resolve_hits`` with the choice made for the number. A choice that is none of the hits any more is forgotten."""
        with self._lock:
            chosen = self._chosen.get(self._key(workspace_id, number), "")
            if chosen and not any(hit["id"] == chosen for hit in hits):
                self._chosen.pop(self._key(workspace_id, number), None)
                chosen = ""
        return resolve_hits(hits, number, chosen)


class ItemService:
    """Finds and reads items of a workspace through an ``FmClient``.

    ``revision`` is the version of each item that searches list: ``WORKING`` (the default) or ``LATEST`` (see ``search_query``). The add-in
    works on the working version throughout: what a publish or an export changes, and what the panels show and compare, is the one
    version a change can reach (a released version cannot be changed)."""

    def __init__(self, client: FmClient, revision: int = WORKING) -> None:
        self._client, self._revision = client, revision

    def search(self, workspace_id: str, item_number: str) -> List[Hit]:
        """Items of the workspace whose descriptor matches ``item_number``, as ``{"id", "descriptor"}``."""
        if not item_number:
            return []
        query = f"itemDescriptor={_quoted(item_number)} AND (workspaceId={workspace_id})"
        data = self._client.get_json(_page_path(query, 0, SEARCH_LIMIT, self._revision))
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
        wanted = {n.strip().lower() for n in numbers if n.strip()}
        if not wanted:
            return {}
        terms = " OR ".join(f"itemDescriptor={_quoted(n)}" for n in numbers if n.strip())
        query = f"({terms}) AND (workspaceId={workspace_id})"
        found: Dict[str, List[Dict[str, Any]]] = {}
        offset = 0
        while True:
            data = self._client.get_json(_page_path(query, offset, FIND_PAGE, self._revision), accept=ITEMS_BULK)
            rows = _rows(data)
            for row in rows:
                descriptor = str(next((row[key] for key in DESCRIPTOR_KEYS if row.get(key)), ""))
                item_id = item_id_of(row)
                if item_id and number_key(descriptor) in wanted:
                    found.setdefault(number_key(descriptor), []).append({"id": item_id, "descriptor": descriptor, "values": collect_values(row)})
            offset += FIND_PAGE
            if not rows or offset >= whole(dig(data, "totalCount")):
                break
        log.info("Searched %d item number(s) in workspace %s: %d found", len(wanted), workspace_id, len(found))
        return found

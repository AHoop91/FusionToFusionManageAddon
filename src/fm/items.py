"""Search for and read Fusion Manage items.

Used to show what already exists in Fusion Manage next to the Manufacturing
Data Model values. Items are found by item number through the search API, then their fields
are read back.

The item JSON is walked generically for ``.../fields/<FIELD_ID>`` entries, so
the reader does not depend on how a workspace groups its fields into sections.
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmClient

log = get_logger("fm.items")

SEARCH_LIMIT = 50      # most items listed for one item number
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


def _hits(data: Any) -> List[Dict[str, str]]:
    """``{"id", "descriptor"}`` for each item of a search-results answer."""
    rows = data.get("items") if isinstance(data, dict) else None
    hits = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for key in ("__self__", "link", "urn"):
            match = _ITEM_ID.search(str(row.get(key, "")))
            if match:
                hits.append({"id": match.group(1), "descriptor": str(row.get("descriptor") or match.group(1))})
                break
    return hits


def pick_hit(hits: List[Dict[str, str]], number: str) -> Dict[str, str]:
    """The hit whose descriptor starts with exactly ``number`` (``9410-306 - STEP``), else the first; ``hits`` must not be empty."""
    wanted = number.strip().lower()
    for hit in hits:
        if hit["descriptor"].split(" - ", 1)[0].strip().lower() == wanted:
            return hit
    return hits[0]


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

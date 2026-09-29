"""Find and read one Fusion Manage item.

Used to show what already exists in Fusion Manage next to the Manufacturing
Data Model values. The item is found by the match-key field, then its fields
are read back as display text.

The item JSON is walked generically for ``.../fields/<FIELD_ID>`` entries, so
the reader does not depend on how a workspace groups its fields into sections.
"""

import re
from typing import Any, Dict, Optional
from urllib.parse import quote

from ..core.logging_setup import get_logger
from .client import FmClient

log = get_logger("fm.items")

SEARCH_LIMIT = 5       # candidates fetched for one match value
ITEM_VIEW = 1          # view 1 holds the item's fields, like the workspace field list
_FIELD_ID = re.compile(r"/fields/([^/]+)/?$")
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


def collect_fields(node: Any, found: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Every ``field id -> display text`` found anywhere in an item's JSON."""
    found = {} if found is None else found
    if isinstance(node, dict):
        match = _FIELD_ID.search(str(node.get("__self__", "")))
        if match and "value" in node:
            found[match.group(1)] = display_text(node["value"])
        for child in node.values():
            collect_fields(child, found)
    elif isinstance(node, list):
        for child in node:
            collect_fields(child, found)
    return found


def _item_ids(data: Any) -> list:
    """Item ids from a search result, whatever key carries the item link."""
    rows = data.get("items") if isinstance(data, dict) else data
    ids = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for key in ("link", "__self__", "urn"):
            match = _ITEM_ID.search(str(row.get(key, "")))
            if match:
                ids.append(match.group(1))
                break
    return ids


class ItemService:
    """Finds items of a workspace through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def find(self, workspace_id: str, match_field_id: str, match_value: str) -> Optional[Dict[str, Any]]:
        """The item whose ``match_field_id`` equals ``match_value``.

        Returns ``{"id": ..., "fields": {field id: text}}`` or ``None``. Search
        hits are verified against the exact value, so a fuzzy search cannot
        return a different item.
        """
        if not match_value:
            return None
        query = quote(f'{match_field_id}="{match_value}"', safe="")
        hits = self._client.get_json(
            f"/api/v3/workspaces/{workspace_id}/items?limit={SEARCH_LIMIT}&query={query}")
        for item_id in _item_ids(hits)[:SEARCH_LIMIT]:
            detail = self._client.get_json(
                f"/api/v3/workspaces/{workspace_id}/items/{item_id}/views/{ITEM_VIEW}")
            fields = collect_fields(detail)
            if fields.get(match_field_id, "").strip().lower() == match_value.strip().lower():
                log.info("Matched item %s in workspace %s", item_id, workspace_id)
                return {"id": item_id, "fields": fields}
        return None

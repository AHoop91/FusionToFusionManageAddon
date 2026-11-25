"""Read Fusion Manage items.

Used to show what already exists in Fusion Manage next to the Manufacturing
Data Model values. An item is found by item number with ``v3_search.ItemFinder``, then its fields are read back here.

The item JSON is walked generically for ``.../fields/<FIELD_ID>`` entries, so
the reader does not depend on how a workspace groups its fields into sections.
"""

from typing import Any, Dict, Optional, Tuple

from ..core.i18n import t
from .client import WORKSPACES, FmApiError, FmClient
from .pages import DESCRIPTOR_KEYS, FIELD_ID


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


class ItemService:
    """Reads items of a workspace through an ``FmClient``. Finding them by number is ``v3_search.ItemFinder``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str) -> Dict[str, Any]:
        """The item's fields as ``{field id: value}``, picklists as Fusion Manage holds them (``display_values`` gives the text)."""
        return self.read_named(workspace_id, item_id)[1]

    def urn(self, workspace_id: str, item_id: str) -> str:
        """The item's urn ("" when the answer holds none), from one read of the item (no layouts or pictures)."""
        return str(self.item(workspace_id, item_id).get("urn") or "")

    def item(self, workspace_id: str, item_id: str) -> Dict[str, Any]:
        """The item as Fusion Manage answers it; raises ``FmApiError`` when the answer is not an item."""
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}")
        if not isinstance(data, dict):
            raise FmApiError(t("data.fm_no_item", item=item_id, workspace=workspace_id))
        return data

    def read_named(self, workspace_id: str, item_id: str) -> Tuple[str, Dict[str, Any]]:
        """``(descriptor, fields)`` of the item, from one read: the descriptor is "" when the answer holds none; raises ``FmApiError`` when the answer is not an item."""
        data = self.item(workspace_id, item_id)
        return str(next((data[key] for key in DESCRIPTOR_KEYS if data.get(key)), "")), collect_values(data)

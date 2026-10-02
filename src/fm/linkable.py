"""Items that can be added to a Fusion Manage item's Bill of Materials.

The Add dialog of Fusion Manage reads ``linkable-items`` of the item in the BOM view (view 5),
one page at a time. Each page is reduced to the few fields the picker draws.
"""

import re
from typing import Any, Dict, List
from urllib.parse import quote

from .bom import _name_of, _number_of
from .client import FmClient

PAGE_SIZE = 100
SORT_DIRECTIONS = ("asc", "desc")
BOM_VIEW_ID = "5"   # the Bill of Materials view is always view 5


def _title(node: Any) -> str:
    return str(node.get("title", "")) if isinstance(node, dict) else ""


def parse_page(data: Any) -> Dict[str, Any]:
    """``{"total", "count", "items": [{"id", "link", "number", "name", "version", "workspace", "lifecycle"}]}``."""
    data = data if isinstance(data, dict) else {}
    items: List[Dict[str, str]] = []
    for row in data.get("items") or []:
        item = row.get("item") if isinstance(row, dict) else None
        if not isinstance(item, dict):
            continue
        link = str(item.get("link", ""))
        match = re.search(r"/items/(\d+)", link)
        if not match:
            continue
        title = str(item.get("title", ""))
        items.append({"id": match.group(1), "link": link, "number": _number_of(title), "name": _name_of(title) or title,
                      "version": str(item.get("version", "")), "workspace": _title(row.get("workspace")),
                      "lifecycle": _title(row.get("lifecycle"))})
    return {"total": int(data.get("totalCount") or 0), "count": len(items), "items": items}


class LinkableService:
    """Reads linkable items through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def page(self, workspace_id: str, item_id: str, offset: int, sort: str) -> Dict[str, Any]:
        """One page of the items that can be added to ``item_id``'s BOM, sorted by title (``asc`` or ``desc``)."""
        direction = sort if sort in SORT_DIRECTIONS else "asc"
        path = (f"/api/v3/workspaces/{workspace_id}/items/{item_id}/views/{BOM_VIEW_ID}/linkable-items"
                f"?limit={PAGE_SIZE}&offset={int(offset)}&relatedWorkspaceId={workspace_id}&sort={quote('item.title ' + direction)}")
        return parse_page(self._client.get_json(path))

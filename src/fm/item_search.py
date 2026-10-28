"""Search the Items workspace for items to add to a Fusion Manage item's Bill of Materials.

The Add Items picker sends free text and filter groups (see ``search_query``); one page of the matches is read
through the search API and reduced to the few fields the picker draws. A search answer has no linkable-items row,
so the row that adding an item to a BOM posts back is written here from the ids, as Fusion Manage would answer it
(the tenant is filled in when the request is sent, see ``placeholders``).
"""

import re
from datetime import date
from typing import Any, Dict, List

from .bom import ACCEPT, WORKING_BIAS, name_of, number_of
from .client import WORKSPACES, FmClient
from .linkable import linkable_row
from .search_query import search_path

PAGE_SIZE = 50
_ITEM_ID = re.compile(r"/items/(\d+)")
_REVISION = re.compile(r"\[REV:([^\]]*)\]\s*$")
_REV_LABEL = re.compile(r"^\s*\[?\s*(?:REV:?)?\s*([^\]]*?)\s*\]?\s*$", re.IGNORECASE)


def _revision_label(raw: Any) -> str:
    """The revision letter alone: Fusion Manage may send ``W``, ``REV:W`` or ``[REV:W]``."""
    match = _REV_LABEL.match(str(raw or ""))
    return match.group(1) if match else str(raw or "")


def parse_search(data: Any, workspace_id: str, parent_id: str) -> Dict[str, Any]:
    """``{"total", "raw", "items": [{"id", "link", "number", "name", "version", "linkable"}]}`` of a search answer.

    ``raw`` is how many rows the page held, to continue from: the parent item is left out of ``items`` (it cannot hold
    itself; there is none while the design is not in Fusion Manage) and ``total`` is as the search counted, so it is one too high once the parent is among the matches."""
    data = data if isinstance(data, dict) else {}
    items: List[Dict[str, Any]] = []
    rows = data.get("items") if isinstance(data.get("items"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        match = None
        for key in ("__self__", "link", "urn"):
            match = _ITEM_ID.search(str(row.get(key, "")))
            if match:
                break
        if not match or match.group(1) == str(parent_id):
            continue
        item_id = match.group(1)
        title = str(row.get("descriptor") or row.get("itemDescriptor") or row.get("title") or item_id)
        found = _REVISION.search(title)
        version = _revision_label(row.get("version") or row.get("revision") or (found.group(1) if found else ""))
        items.append({"id": item_id, "link": f"{WORKSPACES}/{workspace_id}/items/{item_id}",
                      "number": number_of(title), "name": name_of(title) or title, "version": version,
                      "linkable": linkable_row(workspace_id, parent_id, item_id) if parent_id else None})   # no parent yet: the publish writes the row once it exists
    return {"total": int(data.get("totalCount") or data.get("totalHits") or 0), "raw": len(rows), "items": items}


def parse_members(data: Any) -> Dict[str, List[str]]:
    """``{"ids", "numbers"}`` of the nodes of a bulk BOM answer."""
    ids: List[str] = []
    numbers: List[str] = []
    for node in data.get("nodes") or [] if isinstance(data, dict) else []:
        item = node.get("item") if isinstance(node, dict) else None
        if not isinstance(item, dict):
            continue
        match = _ITEM_ID.search(str(item.get("link", "")))
        if match:
            ids.append(match.group(1))
        number = number_of(str(item.get("title", "")))
        if number:
            numbers.append(number)
    return {"ids": ids, "numbers": numbers}


class ItemSearchService:
    """Searches the Items workspace through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def page(self, workspace_id: str, parent_id: str, text: str, groups: Any, offset: int, revision: int = 1) -> Dict[str, Any]:
        """One page of the items matching ``text`` and the filter ``groups``, from ``offset``, oldest first; ``revision`` is as in ``search_path``."""
        data = self._client.get_json(search_path(workspace_id, text, groups, offset, PAGE_SIZE, revision))
        return parse_search(data, workspace_id, parent_id)

    def members(self, workspace_id: str, item_id: str) -> Dict[str, List[str]]:
        """``{"ids", "numbers"}`` of the items the Bill of Materials of ``item_id`` holds now (the item itself included).

        It is the working Bill of Materials of ``item_id``, the one a publish changes. A line may point at another revision of an item than a
        search finds, so the picker matches on the number too."""
        path = (f"{WORKSPACES}/{workspace_id}/items/{item_id}/bom"
                f"?depth=1&effectiveDate={date.today().isoformat()}&revisionBias={WORKING_BIAS}&rootId={item_id}")
        return parse_members(self._client.get_json(path, accept=ACCEPT))

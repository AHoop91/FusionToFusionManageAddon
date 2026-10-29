"""Search the Items workspace for items to add to a Fusion Manage item's Bill of Materials.

The Add Items picker sends free text and filter groups (see ``search_query``); one page of the matches is read
through the search API and reduced to the few fields the picker draws. A search answer has no linkable-items row,
so the row that adding an item to a BOM posts back is written here from the ids, as Fusion Manage would answer it
(the tenant is filled in when the request is sent, see ``placeholders``).
"""

import re
from datetime import date
from typing import Any, Dict, List

from ..core.shapes import as_dict, as_list, dict_rows, dig, whole
from .bom import ACCEPT, WORKING_BIAS, name_of, number_of
from .client import WORKSPACES, FmClient
from .items import DESCRIPTOR_KEYS, item_id_of
from .linkable import linkable_row
from .search_query import search_path

PAGE_SIZE = 25   # rows asked of the search at a time; the picker also reads on until this many rows are visible (see ``page``)
MEMBERS_DEPTH = 1   # levels of the Bill of Materials read for its members: the lines directly under the item
_ITEM_ID = re.compile(r"/items/(\d+)")
_TRAILING_REVISION = re.compile(r"\[REV:([^\]]*)\]\s*$")   # the ``[REV:w]`` that ends a title
_REV_LABEL = re.compile(r"^\s*\[?\s*(?:REV:?)?\s*([^\]]*?)\s*\]?\s*$", re.IGNORECASE)


def _revision_label(raw: Any) -> str:
    """The revision letter alone: Fusion Manage may send ``W``, ``REV:W`` or ``[REV:W]``."""
    match = _REV_LABEL.match(str(raw or ""))
    return match.group(1) if match else str(raw or "")


def _version(row: Dict[str, Any], title: str) -> str:
    """The revision a search row is of: its own field, else the ``[REV:x]`` its title ends with."""
    ending = _TRAILING_REVISION.search(title)
    return _revision_label(row.get("version") or row.get("revision") or (ending.group(1) if ending else ""))


def parse_search(data: Any, workspace_id: str, parent_id: str) -> Dict[str, Any]:
    """``{"total", "raw", "items": [{"id", "link", "number", "name", "version", "linkable"}]}`` of a search answer.

    ``raw`` is how many rows the page held, to continue from. The parent item is left out of ``items`` (it cannot hold itself; there
    is none while the design is not in Fusion Manage), and ``total`` is as the search counted it, so it is one too high once the parent
    is among the matches. ``linkable`` is None while there is no parent: the publish writes the row once the parent exists.
    """
    data = as_dict(data)
    rows = as_list(data.get("items"))
    items: List[Dict[str, Any]] = []
    for row in dict_rows(rows):
        item_id = item_id_of(row)
        if not item_id or item_id == str(parent_id):
            continue
        title = str(next((row[key] for key in DESCRIPTOR_KEYS if row.get(key)), item_id))
        items.append({"id": item_id, "link": f"{WORKSPACES}/{workspace_id}/items/{item_id}",
                      "number": number_of(title), "name": name_of(title) or title, "version": _version(row, title),
                      "linkable": linkable_row(workspace_id, parent_id, item_id) if parent_id else None})
    return {"total": whole(data.get("totalCount") or data.get("totalHits")), "raw": len(rows), "items": items}


def parse_members(data: Any) -> Dict[str, List[str]]:
    """``{"ids", "numbers"}`` of the nodes of a bulk BOM answer."""
    ids: List[str] = []
    numbers: List[str] = []
    for node in dict_rows(dig(data, "nodes")):
        item = as_dict(node.get("item"))
        match = _ITEM_ID.search(str(item.get("link") or ""))
        if match:
            ids.append(match.group(1))
        number = number_of(str(item.get("title") or ""))
        if number:
            numbers.append(number)
    return {"ids": ids, "numbers": numbers}


class ItemSearchService:
    """Searches the Items workspace through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def page(self, workspace_id: str, parent_id: str, text: str, groups: Any, offset: int, revision: int = 1) -> Dict[str, Any]:
        """One page of the items matching ``text`` and the filter ``groups``, from ``offset``, oldest first; ``revision`` is as in ``search_path``.

        The answer is that of ``parse_search`` and ``limit``, how many rows a page holds: the picker keeps reading pages until that many
        rows are visible, so a page whose items are mostly hidden (already in the Bill of Materials) does not leave the list short.
        """
        data = self._client.get_json(search_path(workspace_id, text, groups, offset, PAGE_SIZE, revision))
        return {**parse_search(data, workspace_id, parent_id), "limit": PAGE_SIZE}

    def members(self, workspace_id: str, item_id: str) -> Dict[str, List[str]]:
        """``{"ids", "numbers"}`` of the items the Bill of Materials of ``item_id`` holds now (the item itself included).

        It is the working Bill of Materials of ``item_id``, the one a publish changes. A line may point at another revision of an item than a
        search finds, so the picker matches on the number too."""
        path = (f"{WORKSPACES}/{workspace_id}/items/{item_id}/bom"
                f"?depth={MEMBERS_DEPTH}&effectiveDate={date.today().isoformat()}&revisionBias={WORKING_BIAS}&rootId={item_id}")
        return parse_members(self._client.get_json(path, accept=ACCEPT))

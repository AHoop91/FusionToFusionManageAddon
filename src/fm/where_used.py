"""Where an item is used: the assemblies (parents) that hold it, one level at a time.

``GET /api/v3/workspaces/{ws}/items/{id}/where-used?depth=1`` answers with ``nodes`` (the items) and ``edges``
(who holds whom). The item itself is among the nodes. An edge's ``edgeLink`` is the address of the next level up
from that parent; adding ``depth=1`` to it reads just that level.
"""

import re
from typing import Any, Dict, List

from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, dict_rows
from .bom import split_title
from .client import WORKSPACES, FmApiError, FmClient
from .pages import item_page

log = get_logger("fm.where_used")

HIDDEN_FIELDS = ("DESCRIPTOR",)   # the item's title already says it
_DEPTH = re.compile(r"([?&])depth=\d+&?")


def _fields(node: Dict[str, Any]) -> Dict[str, str]:
    """``{title: value as text}`` of a node's fields, without the ones the title already says."""
    fields = {}
    for field in dict_rows(node.get("fields")):
        if field.get("title") and field["title"] not in HIDDEN_FIELDS:
            fields[str(field["title"])] = "" if field.get("value") is None else str(field["value"])
    return fields


def _one_level(link: str) -> str:
    """``link`` asking for one level only ("" when there is no link)."""
    if not link:
        return ""
    link = _DEPTH.sub(r"\1", link).rstrip("?&")
    return f"{link}{'&' if '?' in link else '?'}depth=1"


def _row(item: Dict[str, Any], fields: Dict[str, str], up: str, base_url: str) -> Dict[str, Any]:
    """The row of one parent: ``up`` is the ``edgeLink`` of the edge to it, "" when nothing holds it (so there is nothing to open)."""
    title = str(item.get("title") or "")
    number, name = split_title(title)
    return {"title": title, "number": number, "name": name, "version": str(item.get("version") or ""), "fields": fields,
            "url": item_page(base_url, item), "up": _one_level(up)}


def parse_where_used(data: Any, base_url: str) -> Dict[str, Any]:
    """Rows (one per parent that holds the item) and the field titles that make the columns, in the order first seen."""
    if data is None:   # 204: nothing holds the item
        return {"rows": [], "columns": []}
    if not (isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("edges"), list)):
        raise FmApiError("Fusion Manage did not return where this item is used.")
    nodes = {}
    for node in dict_rows(data["nodes"]):
        item = as_dict(node.get("item"))
        if item.get("urn"):
            nodes[str(item["urn"])] = (node, item)
    rows: List[Dict[str, Any]] = []
    columns: Dict[str, None] = {}   # the titles in the order first seen
    for edge in dict_rows(data["edges"]):
        found = nodes.get(str(edge.get("child") or ""))
        if found is None:
            continue
        node, item = found
        fields = _fields(node)
        columns.update(dict.fromkeys(fields))
        rows.append(_row(item, fields, str(edge.get("edgeLink") or ""), base_url))
    return {"rows": rows, "columns": list(columns)}


class WhereUsedService:
    """Reads where an item is used through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str, up: str = "") -> Dict[str, Any]:
        """The parents of an item, or (with ``up``, an ``edgeLink`` from an earlier answer) of one of those parents."""
        if up and not up.startswith(WORKSPACES + "/"):   # it came from the page: it must stay inside the API
            raise ValueError("That is not a Fusion Manage where-used address.")
        address = up or f"{WORKSPACES}/{workspace_id}/items/{item_id}/where-used?depth=1"
        return parse_where_used(self._client.get_json(address), self._client.base_url)

"""Where an item is used: the assemblies (parents) that hold it, one level at a time.

``GET /api/v3/workspaces/{ws}/items/{id}/where-used?depth=1`` answers with ``nodes`` (the items) and ``edges``
(who holds whom). The item itself is among the nodes. An edge's ``edgeLink`` is the address of the next level up
from that parent; adding ``depth=1`` to it reads just that level.
"""

import re
from typing import Any, Dict, List, Tuple

from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmApiError, FmClient
from .pages import item_page

log = get_logger("fm.where_used")

HIDDEN_FIELDS = ("DESCRIPTOR",)   # the item's title already says it
_REVISION = re.compile(r"\s*\[REV:[^\]]*\]\s*$")   # the revision the descriptor ends with; the version column says it
_DEPTH = re.compile(r"([?&])depth=\d+&?")


def _fields(node: Dict[str, Any]) -> Dict[str, str]:
    fields = {}
    for field in node.get("fields") if isinstance(node.get("fields"), list) else []:
        if isinstance(field, dict) and field.get("title") and field["title"] not in HIDDEN_FIELDS:
            fields[str(field["title"])] = "" if field.get("value") is None else str(field["value"])
    return fields


def split_title(title: str) -> Tuple[str, str]:
    """``("9410-306", "STEP")`` from a descriptor such as ``9410-306 - STEP [REV:w]`` (the number is "" if there is no " - ")."""
    text = _REVISION.sub("", title).strip()
    number, dash, name = text.partition(" - ")
    return (number.strip(), name.strip()) if dash else ("", text)


def _one_level(link: str) -> str:
    """``link`` asking for one level only ("" when there is no link)."""
    if not link:
        return ""
    link = _DEPTH.sub(r"\1", link).rstrip("?&")
    return f"{link}{'&' if '?' in link else '?'}depth=1"


def parse_where_used(data: Any, base_url: str) -> Dict[str, Any]:
    """Rows (one per parent that holds the item) and the field titles that make the columns, in the order first seen."""
    if data is None:   # 204: nothing holds the item
        return {"rows": [], "columns": []}
    if not (isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("edges"), list)):
        raise FmApiError("Fusion Manage did not return where this item is used.")
    nodes = {}
    for node in data["nodes"]:
        item = node.get("item") if isinstance(node, dict) and isinstance(node.get("item"), dict) else {}
        if item.get("urn"):
            nodes[str(item["urn"])] = (node, item)
    rows: List[Dict[str, Any]] = []
    columns: List[str] = []
    for edge in data["edges"]:
        found = nodes.get(str(edge.get("child") or "")) if isinstance(edge, dict) else None
        if found is None:
            continue
        node, item = found
        fields = _fields(node)
        for title in fields:
            if title not in columns:
                columns.append(title)
        up = str(edge.get("edgeLink") or "")   # no link: nothing holds this parent, so there is nothing to open
        title = str(item.get("title") or "")
        number, name = split_title(title)
        rows.append({
            "title": title,
            "number": number,
            "name": name,
            "version": str(item.get("version") or ""),
            "fields": fields,
            "url": item_page(base_url, item),
            "up": _one_level(up),
        })
    return {"rows": rows, "columns": columns}


class WhereUsedService:
    """Reads where an item is used through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str, up: str = "") -> Dict[str, Any]:
        """The parents of an item, or (with ``up``, an ``edgeLink`` from an earlier answer) of one of those parents."""
        if up:
            if not up.startswith(WORKSPACES + "/"):
                raise ValueError("That is not a Fusion Manage where-used address.")
            address = up
        else:
            address = f"{WORKSPACES}/{workspace_id}/items/{item_id}/where-used?depth=1"
        return parse_where_used(self._client.get_json(address), self._client.base_url)

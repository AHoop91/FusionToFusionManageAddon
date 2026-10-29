"""The requests that change an item's Bill of Materials.

What only Fusion Manage knows when the requests are written is a marker in them, filled in as each is sent: ``{{item:<number>}}`` an item's id
(an item this run creates has none yet), ``{{version:<number>}}`` its revision, ``{{edge:...}}`` a BOM line's id and ``{{tenant}}`` the
tenant code of an urn (see ``placeholders``). Pure functions, no I/O.
"""

from typing import Any, Dict, List, Optional

from ..fm.client import WORKSPACES
from ..fm.linkable import item_link, item_urn, linkable_row
from .placeholders import EDGE, ITEM, VERSION, marker

BOM_ORDER = {"remove": 0, "renumber": 1, "update": 2, "add": 3}   # a line is freed before another takes its number
UNORDERED = len(BOM_ORDER)   # where an operation of a kind not listed sorts: last (and then no request is made for it)


def _edge(parent: str, op: Dict[str, Any], sequence: Any) -> str:
    """The line's id in Fusion Manage, or a marker for it (by the ``sequence`` the line has there now) when the BOM read did not give one."""
    return str(op.get("edge") or "") or marker(EDGE, f"{parent}>{op['number']}@{sequence}")


def _line_number(sequence: Any) -> Any:
    """The BOM item number as a number when it is one (Fusion Manage takes ``1``, not ``"1"``)."""
    text = str(sequence).strip()
    return int(text) if text.isascii() and text.isdigit() else sequence


def _quantity(op: Dict[str, Any]) -> Dict[str, str]:
    """``{"quantity": text}`` for the quantity the operation gives, as Fusion Manage takes it; empty when it gives none, so a request never
    sends a blank quantity (which would clear the line's)."""
    text = str(op.get("quantity") if op.get("quantity") is not None else "").strip()
    return {"quantity": text} if text else {}


def _item_ref(workspace_id: str, number: str) -> Dict[str, Any]:
    """How a line names its item: by the markers of the item's id and version (the item may be one this run creates)."""
    item = marker(ITEM, number)
    return {"link": item_link(workspace_id, item), "urn": item_urn(workspace_id, item), "title": str(number), "deleted": False,
            "version": marker(VERSION, number)}


def _add_body(workspace_id: str, op: Dict[str, Any]) -> Dict[str, Any]:
    """Body that adds a line: the linkable-items row of the picked item (``__self__``, ``urn``, ``item``), else just the item's link."""
    body = dict(op.get("linkable") or {})
    if not body:   # an item this run creates: written as Fusion Manage will answer it, ids and tenant filled in when sent
        body = linkable_row(workspace_id, marker(ITEM, op["parent"]), marker(ITEM, op["number"]))
        item = _item_ref(workspace_id, op["number"])
        body["item"] = {**item, "link": op.get("link") or item["link"]}   # an item picked in Fusion Manage keeps the link it was picked by
    body.update({"itemNumber": _line_number(op.get("sequence", "")), **_quantity(op), "children": [], "fields": []})
    return body


def _line_body(workspace_id: str, op: Dict[str, Any], url: str, **fields: Any) -> Dict[str, Any]:
    """Body that changes a line, shaped as Fusion Manage's own BOM tab sends it: the line (``__self__``), its item and the changed fields.
    A body of the changed field alone was answered with a 500."""
    return {"__self__": url, "item": _item_ref(workspace_id, op["number"]), **fields, "children": [], "fields": []}


def bom_requests(workspace_id: str, operations: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Requests per parent item number from the BOM operations the panel resolved.

    An operation is ``{op, parent, number, quantity, sequence, from_sequence}`` where ``op`` is

    * ``add``: a line for the item ``number`` at ``sequence`` (an item picked in Fusion Manage also has its ``link`` and ``linkable`` row);
    * ``update``: the line's ``quantity`` (an update with none has nothing to change and makes no request);
    * ``renumber``: the line moves from ``from_sequence`` to ``sequence``;
    * ``remove``: the line goes.

    The last three also have the line's ``edge`` id when the BOM read gave one. Lines only Fusion Manage has, with no operation, are never
    touched. A blank ``quantity`` is left out of a request, never sent.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for op in sorted(operations, key=lambda o: BOM_ORDER.get(o["op"], UNORDERED)):
        request = _request(workspace_id, op)
        if request:
            out.setdefault(op["parent"], []).append(request)
    return out


def _request(workspace_id: str, op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The one request an operation makes, or None when it makes none (a kind not listed, or an update with no quantity)."""
    parent, kind, sequence = op["parent"], op["op"], op.get("sequence", "")
    base = f"{WORKSPACES}/{workspace_id}/items/{marker(ITEM, parent)}/bom-items"
    if kind == "add":
        return {"method": "POST", "url": base, "body": _add_body(workspace_id, op)}
    if kind == "remove":
        return {"method": "DELETE", "url": f"{base}/{_edge(parent, op, sequence)}", "body": None}
    if kind == "update":
        if not _quantity(op):
            return None
        url = f"{base}/{_edge(parent, op, sequence)}"
        return {"method": "PATCH", "url": url, "body": _line_body(workspace_id, op, url, **_quantity(op))}
    if kind == "renumber":   # the line is found by the number it has now, which is not the one it is given
        url = f"{base}/{_edge(parent, op, op.get('from_sequence', ''))}"
        changes = {"itemNumber": _line_number(sequence), **_quantity(op)}
        return {"method": "PATCH", "url": url, "body": _line_body(workspace_id, op, url, **changes)}
    return None

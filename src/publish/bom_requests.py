"""The requests that change an item's Bill of Materials.

A ``{{item:<number>}}`` or ``{{edge:...}}`` placeholder stands for an id that is only known when
the request is sent (a new item's id, a BOM line's id); ``{{tenant}}`` and ``{{version:<number>}}`` likewise (see ``placeholders``).
"""

from typing import Any, Dict, List

from ..fm.client import WORKSPACES
from ..fm.linkable import BOM_VIEW_ID

BOM_ORDER = {"remove": 0, "renumber": 1, "update": 2, "add": 3}   # a line is freed before another takes its number


def _edge(parent: str, op: Dict[str, Any], sequence_key: str = "sequence") -> str:
    """The line's id in Fusion Manage, or a placeholder when the BOM read did not give one."""
    return str(op.get("edge") or "") or "{{edge:%s>%s@%s}}" % (parent, op["number"], op.get(sequence_key, ""))


def _line_number(sequence: Any) -> Any:
    """The BOM item number as a number when it is one (Fusion Manage takes ``1``, not ``"1"``)."""
    text = str(sequence).strip()
    return int(text) if text.isdigit() else sequence


def _add_body(workspace_id: str, op: Dict[str, Any]) -> Dict[str, Any]:
    """Body that adds a line: the linkable-items row of the picked item (``__self__``, ``urn``, ``item``), else just the item's link."""
    body = dict(op.get("linkable") or {})
    if not body:   # an item this run creates: written as Fusion Manage will answer it, ids and tenant filled in when sent
        parent, number = f"{{{{item:{op['parent']}}}}}", f"{{{{item:{op['number']}}}}}"
        body = {"__self__": f"{WORKSPACES}/{workspace_id}/items/{parent}/views/{BOM_VIEW_ID}/linkable-items/{number}",
                "urn": f"urn:adsk.plm:tenant.workspace.item.view.linkable-item:{{{{tenant}}}}.{workspace_id}.{parent}.{BOM_VIEW_ID}.{number}",
                "item": {"link": op.get("link") or f"{WORKSPACES}/{workspace_id}/items/{number}",
                         "urn": f"urn:adsk.plm:tenant.workspace.item:{{{{tenant}}}}.{workspace_id}.{number}",
                         "title": str(op["number"]), "deleted": False, "version": f"{{{{version:{op['number']}}}}}"}}
    body.update({"itemNumber": _line_number(op.get("sequence", "")), "quantity": str(op.get("quantity", "")),
                 "children": [], "fields": []})
    return body


def bom_requests(workspace_id: str, operations: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Requests per parent item number from the BOM operations the panel resolved.

    An operation is ``{op, parent, number, quantity, sequence, from_sequence}`` (an ``add`` of an item
    picked in Fusion Manage also has its ``link``) where ``op`` is
    ``add``, ``update`` (quantity), ``remove`` or ``renumber`` (the last three also have the line's ``edge`` id) (a kept Fusion Manage line moves to ``sequence``).
    Lines only Fusion Manage has, with no operation, are never touched.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for op in sorted(operations, key=lambda o: BOM_ORDER.get(o["op"], 9)):
        parent = op["parent"]
        base = f"{WORKSPACES}/{workspace_id}/items/{{{{item:{parent}}}}}/bom-items"
        kind = op["op"]
        if kind == "add":
            request = {"method": "POST", "url": base, "body": _add_body(workspace_id, op)}
        elif kind == "update":
            request = {"method": "PATCH", "url": f"{base}/{_edge(parent, op)}", "body": {"quantity": op.get("quantity", "")}}
        elif kind == "remove":
            request = {"method": "DELETE", "url": f"{base}/{_edge(parent, op)}", "body": None}
        elif kind == "renumber":
            request = {"method": "PATCH", "url": f"{base}/{_edge(parent, op, 'from_sequence')}",
                       "body": {"itemNumber": op.get("sequence", "")}}
        else:
            continue
        out.setdefault(parent, []).append(request)
    return out

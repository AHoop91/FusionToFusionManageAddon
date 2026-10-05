"""The requests that change an item's Bill of Materials.

A ``{{item:<number>}}`` or ``{{edge:...}}`` placeholder stands for an id that is only known when
the request is sent (a new item's id, a BOM line's id).
"""

from typing import Any, Dict, List

from ..fm.client import WORKSPACES

BOM_ORDER = {"remove": 0, "renumber": 1, "update": 2, "add": 3}   # a line is freed before another takes its number


def _edge(parent: str, op: Dict[str, Any], sequence_key: str = "sequence") -> str:
    return "{{edge:%s>%s@%s}}" % (parent, op["number"], op.get(sequence_key, ""))


def bom_requests(workspace_id: str, operations: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Requests per parent item number from the BOM operations the panel resolved.

    An operation is ``{op, parent, number, quantity, sequence, from_sequence}`` (an ``add`` of an item
    picked in Fusion Manage also has its ``link``) where ``op`` is
    ``add``, ``update`` (quantity), ``remove`` or ``renumber`` (a kept Fusion Manage line moves to ``sequence``).
    Lines only Fusion Manage has, with no operation, are never touched.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for op in sorted(operations, key=lambda o: BOM_ORDER.get(o["op"], 9)):
        parent = op["parent"]
        base = f"{WORKSPACES}/{workspace_id}/items/{{{{item:{parent}}}}}/bom-items"
        kind = op["op"]
        if kind == "add":
            request = {"method": "POST", "url": base,
                       "body": {"item": {"link": op.get("link") or f"{WORKSPACES}/{workspace_id}/items/{{{{item:{op['number']}}}}}"},
                                "quantity": op.get("quantity", ""), "itemNumber": op.get("sequence", "")}}
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

"""The Fusion Manage requests a publish would send, as plain dicts.

Each request is ``{"method", "url", "body"}`` with a url relative to the Fusion Manage host.
They are drafts: the body shapes follow the Fusion Manage v3 API but have not been
checked against a tenant. A ``{{item:<number>}}`` or ``{{edge:...}}`` placeholder stands for
an id that is only known when the request is sent (a new item's id, a BOM line's id).
"""

from typing import Any, Dict, List, Optional, Tuple

from ..sync.property_compare import FOUND, MISMATCH, NEW

API = "/api/v3/workspaces"
BOM_ORDER = {"remove": 0, "renumber": 1, "update": 2, "add": 3}   # a line is freed before another takes its number


def _field(workspace_id: str, field_id: str, value: str) -> Dict[str, Any]:
    return {"__self__": f"{API}/{workspace_id}/views/1/fields/{field_id}", "value": value}


def item_request(workspace_id: str, fm: Dict[str, Any], rows: List[Dict[str, Any]],
                 static_values: List[Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """``(request, reason)`` for one item: create it, update what differs, or nothing (request None).

    ``fm`` is the comparison's Fusion Manage info (``state``, ``item_id``) and ``rows`` the
    compared property rows. A new item gets every mapped value and the static values; an
    existing one only the values that differ.
    """
    state = fm.get("state")
    if state == NEW:
        fields = [_field(workspace_id, r["fm_field"], r["value"]) for r in rows if r["status"] == NEW]
        fields += [_field(workspace_id, s.fm_field_id, s.value) for s in static_values if s.fm_field_id]
        return {"method": "POST", "url": f"{API}/{workspace_id}/items", "body": {"fields": fields}}, ""
    if state == FOUND:
        fields = [_field(workspace_id, r["fm_field"], r["value"]) for r in rows if r["status"] == MISMATCH]
        if not fields:
            return None, "Fusion Manage already has the same values."
        return {"method": "PATCH", "url": f"{API}/{workspace_id}/items/{fm.get('item_id')}", "body": {"fields": fields}}, ""
    return None, fm.get("message") or f"Fusion Manage state is {state}."


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
        base = f"{API}/{workspace_id}/items/{{{{item:{parent}}}}}/bom-items"
        kind = op["op"]
        if kind == "add":
            request = {"method": "POST", "url": base,
                       "body": {"item": {"link": op.get("link") or f"{API}/{workspace_id}/items/{{{{item:{op['number']}}}}}"},
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

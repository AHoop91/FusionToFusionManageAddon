"""The request that creates or updates one Fusion Manage item."""

from typing import Any, Dict, List, Optional, Tuple

from ..fm.client import LOOKUPS, WORKSPACES, last_segment
from ..sync.property_compare import FOUND, MISMATCH, NEW


def field_entry(scope: str, field_id: str, value: Any) -> Dict[str, Any]:
    """One field of an item body. A picklist option is sent as a link to it. ``scope`` is the workspace's or the item's link."""
    if isinstance(value, str) and value.startswith(LOOKUPS + "/"):
        value = {"link": value}
    return {"__self__": f"{scope}/views/1/fields/{field_id}", "value": value}


def _by_section(workspace_id: str, fields: List[Tuple[str, Any]], field_sections: Dict[str, str],
                item_id: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    """The item body ``{"sections": [{"link", "fields": [...]}]}``, or ``(None, reason)`` for a field no section holds.

    A new item takes the workspace's own sections and fields. An item that exists reports its sections as
    its own (``.../items/<id>/views/1/sections/551``) and Fusion Manage refuses the workspace's link for it
    ("Could not find section"), so an update (``item_id``) names the item's.
    """
    missing = sorted({fid for fid, _ in fields if fid not in field_sections})
    if missing:
        return None, "Not in any section of workspace " + workspace_id + ": " + ", ".join(missing) + f" (the workspace lists {len(field_sections)} fields in its sections)."
    scope = f"{WORKSPACES}/{workspace_id}" + (f"/items/{item_id}" if item_id else "")
    sections: Dict[str, List[Dict[str, Any]]] = {}
    for field_id, value in fields:
        sections.setdefault(field_sections[field_id], []).append(field_entry(scope, field_id, value))
    own = {link: f"{scope}/views/1/sections/{last_segment(link)}" if item_id else link for link in sections}
    return {"sections": [{"link": own[link], "fields": items} for link, items in sections.items()]}, ""


def item_request(workspace_id: str, fm: Dict[str, Any], rows: List[Dict[str, Any]], static_values: List[Any],
                 field_sections: Dict[str, str], files: Optional[List[Tuple[str, Any]]] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """``(request, reason)`` for one item: create it (POST), update what differs (PATCH), or nothing (request None).

    ``fm`` is the comparison's Fusion Manage info (``state``, ``item_id``) and ``rows`` the
    compared property rows. The static values are always sent, on a new item and on an existing one.
    A new item also gets every mapped value that has one; an existing one only the mapped values that
    differ. ``files`` are (field id, value) pairs for image fields; they cannot be compared, so they are
    sent on every create and update. ``field_sections`` maps each field id to its section link,
    because Fusion Manage takes the values grouped by section.
    """
    state = fm.get("state")
    statics = [(s.fm_field_id, s.value) for s in static_values if s.fm_field_id] + list(files or [])
    if state == NEW:
        fields = [(r["fm_field"], r["value"]) for r in rows if r["status"] == NEW and r["value"] != ""] + statics
        method, url = "POST", f"{WORKSPACES}/{workspace_id}/items"
    elif state == FOUND:
        fields = [(r["fm_field"], r["value"]) for r in rows if r["status"] == MISMATCH] + statics
        if not fields:
            return None, "Fusion Manage already has the same values."
        method, url = "PATCH", f"{WORKSPACES}/{workspace_id}/items/{fm.get('item_id')}"
    else:
        return None, fm.get("message") or f"Fusion Manage state is {state}."
    body, reason = _by_section(workspace_id, fields, field_sections, str(fm.get("item_id") or "") if state == FOUND else "")
    if body is None:
        return None, reason
    return {"method": method, "url": url, "body": body}, ""

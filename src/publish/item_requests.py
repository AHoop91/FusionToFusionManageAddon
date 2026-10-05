"""The request that creates or updates one Fusion Manage item."""

from typing import Any, Dict, List, Optional, Tuple

from ..sync.property_compare import FOUND, MISMATCH, NEW
from .fm_api import API, field_entry


def _by_section(workspace_id: str, fields: List[Tuple[str, Any]],
                field_sections: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """The item body ``{"sections": [{"link", "fields": [...]}]}``, or ``(None, reason)`` for a field no section holds."""
    missing = sorted({fid for fid, _ in fields if fid not in field_sections})
    if missing:
        return None, "Not in any section of workspace " + workspace_id + ": " + ", ".join(missing) + f" (the workspace lists {len(field_sections)} fields in its sections)."
    sections: Dict[str, List[Dict[str, Any]]] = {}
    for field_id, value in fields:
        sections.setdefault(field_sections[field_id], []).append(field_entry(workspace_id, field_id, value))
    return {"sections": [{"link": link, "fields": items} for link, items in sections.items()]}, ""


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
        method, url = "POST", f"{API}/{workspace_id}/items"
    elif state == FOUND:
        fields = [(r["fm_field"], r["value"]) for r in rows if r["status"] == MISMATCH] + statics
        if not fields:
            return None, "Fusion Manage already has the same values."
        method, url = "PATCH", f"{API}/{workspace_id}/items/{fm.get('item_id')}"
    else:
        return None, fm.get("message") or f"Fusion Manage state is {state}."
    body, reason = _by_section(workspace_id, fields, field_sections)
    if body is None:
        return None, reason
    return {"method": method, "url": url, "body": body}, ""

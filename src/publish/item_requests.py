"""The request that creates or updates one Fusion Manage item.

Layer: domain. Pure builders of the request body from compared rows; no network, no files.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..config.workspace_models import StaticValue
from ..core.i18n import t
from ..fm.client import LOOKUPS, VIEW, WORKSPACES, last_segment
from ..fm.pivots import Derived
from ..fm.items import display_text
from ..sync.property_compare import FOUND, MISMATCH, NEW

Row = Dict[str, Any]   # a compared property row: ``fm_field``, ``value``, ``status``
Fields = List[Tuple[str, Any]]   # (field id, value) pairs, in the order they are sent
Outcome = Tuple[Optional[Dict[str, Any]], str]   # (request, reason): a request, or None and why there is none


def _is_option(value: Any) -> bool:
    """Whether ``value`` is the link of a picklist option."""
    return isinstance(value, str) and value.startswith(LOOKUPS + "/")


def _given(value: Any) -> bool:
    """Whether a mapped value is there to send: a blank one never overwrites what Fusion Manage holds (0 is a value)."""
    return value is not None and str(value).strip() != ""


def field_value(value: Any) -> Any:
    """``value`` as a field takes it in a request: a picklist option is sent as a link to it."""
    return {"link": value} if _is_option(value) else value


def field_entry(scope: str, field_id: str, value: Any) -> Dict[str, Any]:
    """One field of an item body. ``scope`` is the workspace's or the item's link."""
    return {"__self__": f"{scope}/{VIEW}/fields/{field_id}", "value": field_value(value)}


def _by_section(workspace_id: str, fields: Fields, field_sections: Dict[str, str], item_id: str = "") -> Outcome:
    """The item body ``{"sections": [{"link", "fields": [...]}]}``, or ``(None, reason)`` for a field no section holds.

    A new item takes the workspace's own sections and fields. An item that exists reports its sections as
    its own (``.../items/<id>/views/1/sections/551``) and Fusion Manage refuses the workspace's link for it
    ("Could not find section"), so an update (``item_id``) names the item's.
    """
    missing = sorted({field_id for field_id, _ in fields if field_id not in field_sections})
    if missing:
        return None, t("run.request_no_section", workspace=workspace_id, fields=", ".join(missing), count=len(field_sections))
    scope = f"{WORKSPACES}/{workspace_id}" + (f"/items/{item_id}" if item_id else "")
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for field_id, value in fields:
        by_section.setdefault(field_sections[field_id], []).append(field_entry(scope, field_id, value))
    named = (lambda link: f"{scope}/{VIEW}/sections/{last_segment(link)}") if item_id else (lambda link: link)
    return {"sections": [{"link": named(link), "fields": entries} for link, entries in by_section.items()]}, ""


def holds(current: Any, value: Any) -> bool:
    """Whether the item's current value of a field is ``value`` (a picklist option is held as ``{"link": ...}``)."""
    if isinstance(value, dict):   # a link to an item, e.g. the component
        wanted = value.get("link")
    elif _is_option(value):
        wanted = value
    else:
        return display_text(current).strip() == str(value).strip()
    return isinstance(current, dict) and current.get("link") == wanted


def _of_status(rows: List[Row], status: str) -> Fields:
    """The mapped values of the rows with this ``status`` that have a value to send."""
    return [(row["fm_field"], row["value"]) for row in rows if row["status"] == status and _given(row["value"])]


def _fixed_fields(static_values: List[StaticValue], component: Optional[Tuple[str, str, List[Derived]]],
                  field_sections: Dict[str, str]) -> Tuple[Fields, Dict[str, str]]:
    """``(fixed, field_sections)``: the values sent like static values (the static ones, the component link and the derived fields), and the
    sections of the fields, with those of the derived fields added."""
    fixed: Fields = [(s.fm_field_id, s.value) for s in static_values if s.fm_field_id]
    if component:
        component_field, link, derived = component
        fixed.append((component_field, {"link": link}))
        fixed += [(d.field_id, d.value) for d in derived]
        field_sections = {**field_sections, **{d.field_id: d.section for d in derived}}
    return fixed, field_sections


def _update_fields(rows: List[Row], fixed: Fields, files: Fields, current: Optional[Dict[str, Any]]) -> Fields:
    """What an update of an existing item sends: the values that differ, the fixed values it does not hold yet, and the files. Empty when nothing."""
    lacking = [(field_id, value) for field_id, value in fixed if current is None or not holds(current.get(field_id), value)]
    fields = _of_status(rows, MISMATCH) + lacking
    return fields + files if fields or files else []


# ``item_request`` takes 8 parameters: it is the module's one public call, its callers (and their tests) pass them by position, and each is a
# different part of what the request is made from.
def item_request(workspace_id: str, fm: Dict[str, Any], rows: List[Row], static_values: List[StaticValue],
                 field_sections: Dict[str, str], files: Optional[Fields] = None,
                 current: Optional[Dict[str, Any]] = None, component: Optional[Tuple[str, str, List[Derived]]] = None) -> Outcome:
    """``(request, reason)`` for one item: create it (POST), update what differs (PATCH), or nothing (request None).

    ``fm`` is the comparison's Fusion Manage info (``state``, ``item_id``) and ``rows`` the compared property rows. ``field_sections`` maps
    each field id to its section link, because Fusion Manage takes the values grouped by section.

    * A new item gets every mapped value that has one and every static value.
    * An existing one gets the mapped values that differ and the static values it does not hold yet, and nothing at all when none do.
      ``current`` is its values as Fusion Manage holds them; without it every static value is sent.
    * ``files`` are (field id, value) pairs for image fields. They cannot be compared, so they are always sent: with a create, and with an
      update, which they make on their own when nothing else differs.
    * ``component`` is the (field id, link, derived fields) of the component linking field. The link and the derived fields Fusion Manage
      takes from the linked item are sent like static values, so an item that lacks them gets them. Fusion Manage refuses an item that does not
      hold the derived values, and names the section each is written in.
    """
    state = fm.get("state")
    files = list(files or [])
    fixed, field_sections = _fixed_fields(static_values, component, field_sections)
    if state == NEW:
        fields = _of_status(rows, NEW) + fixed + files
        method, url, item_id = "POST", f"{WORKSPACES}/{workspace_id}/items", ""
    elif state == FOUND:
        item_id = str(fm.get("item_id") or "")
        if not item_id:   # an update has to say which item
            return None, t("run.request_no_id")
        fields = _update_fields(rows, fixed, files, current)
        if not fields:
            return None, t("run.request_same_values")
        method, url = "PATCH", f"{WORKSPACES}/{workspace_id}/items/{item_id}"
    else:
        return None, fm.get("message") or t("run.request_state", state=state)
    body, reason = _by_section(workspace_id, fields, field_sections, item_id)
    return ({"method": method, "url": url, "body": body}, "") if body else (None, reason)

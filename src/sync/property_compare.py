"""Compare Manufacturing Data Model properties with a Fusion Manage item.

Each property row gets the Fusion Manage field it is mapped to, that field's
current value, and a status telling the user what publishing would do:

* ``match``: mapped, and the Fusion Manage value is already the same.
* ``mismatch``: mapped, and publishing will change the Fusion Manage value.
* ``new``: mapped, but no Fusion Manage item exists yet; it will be created.
* ``unmapped``: no field mapping uses this property; it is not published.
* ``unknown``: mapped, but the Fusion Manage item could not be read.
* ``unchecked``: mapped, but Fusion Manage has not been looked up (``fm_state`` ``unchecked``).
* ``multiple``: mapped, but several Fusion Manage items match and none is chosen yet.

``fm_state`` is ``found``, ``new`` (no item yet), ``multiple`` (several items, none chosen), ``unknown`` (lookup failed) or ``unchecked``.
"""

from typing import Any, Dict, List, Optional

from ..config.workspace_models import (
    BASE_PREFIX,
    CUSTOM_PREFIX,
    SOURCE_FIELDS,
    FieldMapping,
)

MATCH, MISMATCH, NEW, UNMAPPED, UNKNOWN, UNCHECKED, MULTIPLE = (
    "match", "mismatch", "new", "unmapped", "unknown", "unchecked", "multiple")
FOUND = "found"   # fm_state: the Fusion Manage item exists

_LABELS = {f.field_id: f.label for f in SOURCE_FIELDS if f.kind == "property"}


def source_property_name(source: str) -> str:
    """Name of the Data Model property a mapping source refers to."""
    for prefix in (CUSTOM_PREFIX, BASE_PREFIX):
        if source.startswith(prefix):
            return source[len(prefix):]
    return _LABELS.get(source, "")


def source_value(source: str, summary: Dict[str, Any], values: Dict[str, str]) -> str:
    """Current Data Model value of a mapping source (lower-cased ``values`` keys)."""
    direct = {"part_number": summary.get("part_number", ""),
              "description": summary.get("description", "")}
    if source in direct and direct[source]:
        return str(direct[source])
    return values.get(source_property_name(source).strip().lower(), "")


def _same(left: str, right: str) -> bool:
    return left.strip() == right.strip()


def compare_properties(properties: List[Dict[str, str]], summary: Dict[str, Any],
                       mappings: List[FieldMapping], fm_fields: Optional[Dict[str, str]],
                       fm_state: str) -> List[Dict[str, Any]]:
    """One row per property, plus rows for mapped sources that are not listed."""
    values = {p["name"].strip().lower(): p["value"] for p in properties}
    by_name: Dict[str, FieldMapping] = {}
    for mapping in mappings:
        if mapping.source and mapping.fm_field_id:
            by_name[source_property_name(mapping.source).strip().lower()] = mapping

    names = [(p["name"], p["value"]) for p in properties]
    listed = {n.strip().lower() for n, _ in names}
    for key, mapping in by_name.items():
        if key and key not in listed:   # e.g. "Part number" when the hub lists it differently
            names.append((source_property_name(mapping.source),
                          source_value(mapping.source, summary, values)))

    rows = []
    for name, value in names:
        mapping = by_name.get(name.strip().lower())
        if mapping is None:
            rows.append({"name": name, "value": value, "fm_field": "", "fm_value": "", "status": UNMAPPED})
            continue
        # A mapped built-in (part number, description) may be fresher than the property list.
        value = source_value(mapping.source, summary, values) or value
        fm_value = (fm_fields or {}).get(mapping.fm_field_id, "")
        if fm_state == UNCHECKED:
            status = UNCHECKED
        elif fm_state in (UNKNOWN, MULTIPLE):
            status = fm_state
        elif fm_state != FOUND:
            status = NEW
        else:
            status = MATCH if _same(value, fm_value) else MISMATCH
        rows.append({"name": name, "value": value, "fm_field": mapping.fm_field_id,
                     "fm_value": fm_value, "status": status})
    # Mapped rows first, so what will change is at the top.
    order = {MISMATCH: 0, NEW: 1, MULTIPLE: 2, UNKNOWN: 3, MATCH: 4, UNCHECKED: 5, UNMAPPED: 6}
    return sorted(rows, key=lambda r: (order[r["status"]], r["name"].lower()))

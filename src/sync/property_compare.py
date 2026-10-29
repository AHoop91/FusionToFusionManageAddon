"""Compare Manufacturing Data Model properties with a Fusion Manage item.

Each property row gets the Fusion Manage field it is mapped to, that field's
current value, and a status telling the user what publishing would do:

* ``match``: mapped, and the Fusion Manage value is already the same.
* ``mismatch``: mapped, and publishing will change the Fusion Manage value.
* ``new``: mapped, but no Fusion Manage item exists yet; it will be created.
* ``unmapped``: no field mapping uses this property; it is not published.
* ``unknown``: mapped, but the Fusion Manage item could not be read.
* ``unchecked``: mapped, but Fusion Manage has not been looked up (``fm_state`` ``unchecked``).
* ``multiple``: mapped, but several Fusion Manage items carry the item number, so none is used.

``fm_state`` says how the lookup of the item stands: ``found``, ``new`` (no item yet), ``multiple`` (several items carry the number),
``unknown`` (lookup failed) or ``unchecked``. Apart from ``found``, a state is also the status of every mapped row.
"""

from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config.workspace_models import FieldMapping, data_model_name

MATCH, MISMATCH, NEW, UNMAPPED, UNKNOWN, UNCHECKED, MULTIPLE = (
    "match", "mismatch", "new", "unmapped", "unknown", "unchecked", "multiple")
FOUND = "found"   # fm_state: the Fusion Manage item exists

# fm_state values that give every mapped row the same status as the state itself.
_STATE_IS_STATUS = (NEW, UNKNOWN, UNCHECKED, MULTIPLE)
# Mapping sources that are read from the design's summary when it has them.
_BUILT_IN = ("item_number", "part_number", "description")
# Mapped rows first, so what will change is at the top.
_ORDER = {MISMATCH: 0, NEW: 1, MULTIPLE: 2, UNKNOWN: 3, MATCH: 4, UNCHECKED: 5, UNMAPPED: 6}

FitNumber = Callable[[str, str], str]   # (field id, text) -> the number cut to the digits the field holds
ConvertUnit = Callable[[str, str, str], Optional[Tuple[str, str]]]   # (field id, number, unit) -> (number, unit) in the field's unit


def _key(name: str) -> str:
    """Property names compare without case or spaces: "Material Name" is the Data Model's materialName."""
    return name.replace(" ", "").lower()


def _source_value(source: str, summary: Dict[str, Any], values: Dict[str, str]) -> str:
    """Current Data Model value of a mapping source (``values`` is keyed by ``_key``)."""
    if source in _BUILT_IN and summary.get(source):
        return str(summary[source])
    return values.get(_key(data_model_name(source)), "")


def _same(left: str, right: str, fit: Optional[Callable[[str], str]] = None) -> bool:
    """Equal as text, or as numbers once ``fit`` has cut ``left`` to the digits the Fusion Manage field takes."""
    if left.strip() == right.strip():
        return True
    if fit is None:
        return False
    try:
        return float(fit(left)) == float(right.strip())
    except ValueError:
        return False


def _status(fm_state: str, value: str, fm_value: str, fit: Optional[Callable[[str], str]]) -> str:
    """The status of a mapped row: what publishing does with ``value`` given how the lookup of the item stands."""
    if fm_state in _STATE_IS_STATUS:
        return fm_state
    if fm_state != FOUND:
        raise ValueError(f"Unknown Fusion Manage lookup state: {fm_state!r}")
    # A value Fusion lacks never replaces one Fusion Manage holds: only a real difference is pushed.
    return MATCH if not value.strip() or _same(value, fm_value, fit) else MISMATCH


def _with_unlisted_sources(properties: List[Dict[str, str]], by_name: Dict[str, FieldMapping], summary: Dict[str, Any],
                           values: Dict[str, str]) -> List[Tuple[str, str]]:
    """``(name, value)`` of each property, then of each mapped source the list lacks (e.g. "Part number" when the hub lists it differently)."""
    names = [(p["name"], p["value"]) for p in properties]
    listed = {_key(name) for name, _ in names}
    for key, mapping in by_name.items():
        if key and key not in listed:
            names.append((data_model_name(mapping.source), _source_value(mapping.source, summary, values)))
    return names


def compare_properties(properties: List[Dict[str, str]], summary: Dict[str, Any],
                       mappings: List[FieldMapping], fm_fields: Optional[Dict[str, str]],
                       fm_state: str, fit_number: Optional[FitNumber] = None,
                       convert_unit: Optional[ConvertUnit] = None) -> List[Dict[str, Any]]:
    """One row per property, plus rows for mapped sources that are not listed.

    ``convert_unit(field id, number, unit)`` gives a physical value as ``(number, unit)`` in the unit the Fusion Manage
    field is set to, or None to leave it as it is.

    ``fit_number(field id, text)`` rounds a number to the digits a Fusion Manage field holds, so a value that
    is the same at that precision (0.104455 against 0.104) is a match, not a change.

    Raises ``ValueError`` for an ``fm_state`` that is not one of the states above, rather than reporting it as a new item.
    """
    values = {_key(p["name"]): p["value"] for p in properties}
    extras = {_key(p["name"]): {k: p[k] for k in ("unit", "original") if p.get(k)} for p in properties}   # a physical property's unit and original value
    by_name = {_key(data_model_name(m.source)): m for m in mappings if m.source and m.fm_field_id}
    fm_fields = fm_fields or {}

    rows = []
    for name, value in _with_unlisted_sources(properties, by_name, summary, values):
        mapping = by_name.get(_key(name))
        if mapping is None:
            rows.append({"name": name, "value": value, "fm_field": "", "fm_value": "", "status": UNMAPPED})
            continue
        field = mapping.fm_field_id
        # A mapped built-in (part number, description) may be fresher than the property list.
        value = _source_value(mapping.source, summary, values) or value
        extra = dict(extras.get(_key(name), {}))
        if convert_unit and extra.get("unit") and value:   # a physical value in the unit the field is set to: Fusion's centimetres into millimetres
            converted = convert_unit(field, value, extra["unit"])
            if converted:
                value, extra["unit"] = converted
        fit = partial(fit_number, field) if fit_number else None
        fm_value = fm_fields.get(field, "")
        rows.append({"name": name, "value": value, "shown": fit(value) if fit and value else value, "fm_field": field,
                     "fm_value": fm_value, "status": _status(fm_state, value, fm_value, fit), **extra})
    return sorted(rows, key=lambda r: (_ORDER[r["status"]], r["name"].lower()))

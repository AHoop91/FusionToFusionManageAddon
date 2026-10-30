"""Compare one design or component with its Fusion Manage item (shared by the panel and by publishing)."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, TypedDict

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceConfig
from ..core.logging_setup import get_logger
from ..fm.client import FmApiError, FmClient
from ..fm.items import ItemService, display_values
from ..fm.picklists import PicklistResolver
from ..fm.search_query import WORKING
from .item_number import item_number_of
from .property_compare import FOUND, MULTIPLE, NEW, UNCHECKED, UNKNOWN, ConvertUnit, FitNumber, compare_properties

log = get_logger("item_compare")


class ItemInfo(TypedDict):
    """How the lookup stands, as the panels read it (it is sent to them as it is, so it is a plain object)."""

    state: str                         # ``found``, ``new``, ``multiple``, ``unknown`` or ``unchecked`` (see ``property_compare``)
    message: str                       # why the item could not be compared, for the user ("" when it could)
    item_id: str                       # the Fusion Manage item's id ("" until one is picked)
    item_number: str                   # the number looked up
    candidates: List[Dict[str, Any]]   # the items that carry the number, when several do


class ItemLookup(NamedTuple):
    """What Fusion Manage said about a component's item: ``info`` (state, ids, candidates) and the item's field ``values``, if one was picked."""

    info: ItemInfo
    values: Optional[Dict[str, Any]]


def _new_info(number: str, state: str = UNCHECKED, item_id: str = "") -> ItemInfo:
    return {"state": state, "message": "", "item_id": item_id, "item_number": number, "candidates": []}


def _unreadable(info: ItemInfo, exc: Exception) -> ItemLookup:
    """The lookup when Fusion Manage could not be read: its state is ``unknown`` and there are no values."""
    log.warning("Fusion Manage lookup failed: %s", exc)
    info.update(state=UNKNOWN, message=f"Could not read Fusion Manage: {exc}")
    return ItemLookup(info, None)


def lookup_item(summary: Dict[str, Any], cfg: WorkspaceConfig, fm: FmClient, found: Optional[List[Dict[str, Any]]] = None,
                revision: int = WORKING) -> ItemLookup:
    """Find the component's item in Fusion Manage. Runs on a worker thread.

    ``found`` is what an earlier search already found for the number (hits, each with the item's ``values`` when the search gave them):
    it saves the search, and the read of an item whose values came with it. ``revision`` is the version of the item searched for (see
    ``ItemService``).

    The item is searched by item number in the Items workspace. When several items match, none is used: the state is ``multiple`` and
    ``candidates`` lists them, for the number to be fixed in Fusion Manage. It needs only the component's numbers, so it can run while
    the component's properties are still being read.
    """
    number = item_number_of(summary)
    info = _new_info(number)
    if not cfg.workspace_id:
        info["message"] = "Set the Items workspace ID in Settings to compare with Fusion Manage."
        return ItemLookup(info, None)
    if not number:
        info["message"] = "This component has no item number to look up in Fusion Manage."
        return ItemLookup(info, None)
    values = None
    try:
        service = ItemService(fm, revision)
        hits = found if found is not None else service.search(cfg.workspace_id, number)
        picked = hits[0] if len(hits) == 1 else None
        if picked:
            values = picked.get("values") or service.read(cfg.workspace_id, picked["id"])
    except (FmApiError, AuthError) as exc:
        return _unreadable(info, exc)
    if not hits:
        info["state"] = NEW
    elif picked:
        info.update(state=FOUND, item_id=picked["id"])
    else:
        info.update(state=MULTIPLE, message=f"{len(hits)} Fusion Manage items carry the item number {number}. "
                                            "Renumber or remove the extra items in Fusion Manage.",
                    candidates=[{k: v for k, v in hit.items() if k != "values"} for hit in hits])   # the list, not the values
    return ItemLookup(info, values)


def known_lookup(summary: Dict[str, Any], cfg: WorkspaceConfig, fm: FmClient, item_id: str) -> ItemLookup:
    """The lookup of an item whose id is known (the item panel shows it): its values are read, with no search for it by number."""
    info = _new_info(item_number_of(summary), FOUND, item_id)
    try:
        return ItemLookup(info, ItemService(fm).read(cfg.workspace_id, item_id))
    except (FmApiError, AuthError) as exc:
        return _unreadable(info, exc)


def read_and_compare(read: Callable[[], List[Dict[str, str]]], subject: Dict[str, Any], cfg: WorkspaceConfig, fm: FmClient,
                     known_id: str = "") -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """``(properties, comparison)``: read the properties with ``read`` while Fusion Manage is asked for the item of ``subject``, then compare
    them (``compare_with_item``, with the digits and units of the mapped fields). ``known_id`` is the id of the item when the caller has it,
    which saves the search for it. Runs on a worker thread; the publish panel and the item panel's up-to-date check both use it."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(read)
        # Fusion Manage is asked while the Data Model is read.
        lookup = known_lookup(subject, cfg, fm, known_id) if known_id else lookup_item(subject, cfg, fm)
    properties = pending.result()
    resolver = PicklistResolver(fm, cfg.workspace_id) if cfg.workspace_id else None
    return properties, compare_with_item(properties, subject, cfg, lookup, resolver.fit_number if resolver else None,
                                         convert_unit=resolver.convert_unit if resolver else None)


def compare_with_item(properties: List[Dict[str, str]], summary: Dict[str, Any], cfg: WorkspaceConfig, lookup: ItemLookup,
                      fit_number: Optional[FitNumber] = None, with_values: bool = False,
                      convert_unit: Optional[ConvertUnit] = None) -> Dict[str, Any]:
    """Compare the properties with the item ``lookup`` found. ``fit_number`` rounds a number to the digits its
    Fusion Manage field takes and ``convert_unit`` puts it in the field's unit (see ``compare_properties``).
    ``with_values`` adds the item's raw field values to the answer (``values``), so a caller needs no second read."""
    mappings = [m for m in cfg.mappings if m.source and m.fm_field_id]
    shown = display_values(lookup.values) if lookup.values is not None else None
    rows = compare_properties(properties, summary, mappings, shown, lookup.info["state"], fit_number, convert_unit)
    result: Dict[str, Any] = {"fm": lookup.info, "rows": rows}
    if with_values:
        result["values"] = lookup.values
    return result

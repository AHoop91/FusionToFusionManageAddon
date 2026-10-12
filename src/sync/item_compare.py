"""Compare one design or component with its Fusion Manage item (shared by the panel and by publishing)."""

from typing import Any, Callable, Dict, List, NamedTuple, Optional

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceConfig
from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch
from ..fm.client import FmApiError, FmClient
from ..fm.items import ItemService, display_values
from .property_compare import FOUND, MULTIPLE, NEW, UNKNOWN, compare_properties

log = get_logger("item_compare")


class ItemLookup(NamedTuple):
    """What Fusion Manage said about a component's item: ``info`` (state, ids, candidates) and the item's field ``values``, if one was picked."""

    info: Dict[str, Any]
    values: Optional[Dict[str, Any]]


def item_number_of(summary: Dict[str, Any]) -> str:
    """The number to look a design or component up by in Fusion Manage: its item number ("" when it has none: it is not published)."""
    return str(summary.get("item_number") or "").strip()


def lookup_item(summary: Dict[str, Any], cfg: WorkspaceConfig, fm: FmClient, chosen: str = "") -> ItemLookup:
    """Find the component's item in Fusion Manage. Runs on a worker thread.

    The item is searched by item number in the Items workspace. When several items match, ``chosen`` (an item id the
    user picked) selects one; until then the state is ``multiple`` and ``candidates`` lists them. It needs only the
    component's numbers, so it can run while the component's properties are still being read.
    """
    number = item_number_of(summary)
    info: Dict[str, Any] = {"state": "unchecked", "message": "", "item_id": "", "item_number": number, "candidates": []}
    if not cfg.workspace_id:
        info["message"] = "Set the Items workspace ID in Settings to compare with Fusion Manage."
        return ItemLookup(info, None)
    if not number:
        info["message"] = "This component has no item number to look up in Fusion Manage."
        return ItemLookup(info, None)
    values = None
    try:
        service = ItemService(fm)
        watch = Stopwatch()
        hits = service.search(cfg.workspace_id, number)
        search_seconds = watch.lap()
        picked = next((h for h in hits if h["id"] == chosen), None) or (hits[0] if len(hits) == 1 else None)
        if picked:
            values = service.read(cfg.workspace_id, picked["id"])
        log.debug("Looked up %s in Fusion Manage: search %.2fs (%d hits), read %.2fs", number, search_seconds, len(hits), watch.lap())
    except (FmApiError, AuthError) as exc:
        log.warning("Fusion Manage lookup failed: %s", exc)
        info.update(state=UNKNOWN, message=f"Could not read Fusion Manage: {exc}")
        return ItemLookup(info, None)
    if not hits:
        info.update(state=NEW)
    else:
        info["candidates"] = hits if len(hits) > 1 else []
        if picked:
            info.update(state=FOUND, item_id=picked["id"])
        else:
            info.update(state=MULTIPLE, message=f"{len(hits)} Fusion Manage items match {number}. Choose one.")
    return ItemLookup(info, values)


def compare_with_item(properties: List[Dict[str, str]], summary: Dict[str, Any], cfg: WorkspaceConfig, lookup: ItemLookup,
                      fit_number: Optional[Callable[[str, str], str]] = None, with_values: bool = False) -> Dict[str, Any]:
    """Compare the properties with the item ``lookup`` found. ``fit_number`` rounds a number to the digits its
    Fusion Manage field takes (see ``compare_properties``). ``with_values`` adds the item's raw field values
    to the answer (``values``), so a caller needs no second read."""
    mappings = [m for m in cfg.mappings if m.source and m.fm_field_id]
    shown = display_values(lookup.values) if lookup.values is not None else None
    result = {"fm": lookup.info, "rows": compare_properties(properties, summary, mappings, shown, lookup.info["state"], fit_number)}
    if with_values:
        result["values"] = lookup.values
    return result

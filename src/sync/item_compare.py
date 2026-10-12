"""Compare one design or component with its Fusion Manage item (shared by the panel and by publishing)."""

import time
from concurrent.futures import Future
from typing import Any, Dict, List, Union

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceConfig
from ..core.logging_setup import get_logger
from ..fm.client import FmApiError, FmClient
from ..fm.items import ItemService, display_values
from .property_compare import FOUND, MULTIPLE, NEW, UNKNOWN, compare_properties

log = get_logger("item_compare")


def compare_item(properties: Union[List[Dict[str, str]], "Future[List[Dict[str, str]]]"], summary: Dict[str, Any], cfg: WorkspaceConfig,
                 fm: FmClient, chosen: str = "", with_values: bool = False) -> Dict[str, Any]:
    """Compare the properties with Fusion Manage. Runs on a worker thread.

    ``properties`` may be a future of them: Fusion Manage is asked first, so a read of the properties already
    under way runs at the same time, and its result (or error) is taken once Fusion Manage has answered.

    The item is searched by item number in the Items workspace. When several
    items match, ``chosen`` (an item id the user picked) selects one; until then
    the state is ``multiple`` and ``candidates`` lists them. ``with_values`` adds the item's raw field
    values to the answer (``values``), so a caller needs no second read.
    """
    mappings = [m for m in cfg.mappings if m.source and m.fm_field_id]
    number = str(summary.get("item_number") or summary.get("part_number") or "").strip()
    info: Dict[str, Any] = {"state": "unchecked", "message": "", "item_id": "", "item_number": number,
                            "candidates": []}
    values = None
    if not cfg.workspace_id:
        info["message"] = "Set the Items workspace ID in Settings to compare with Fusion Manage."
    elif not number:
        info["message"] = "This component has no item number to look up in Fusion Manage."
    else:
        try:
            service = ItemService(fm)
            began = time.monotonic()
            hits = service.search(cfg.workspace_id, number)
            searched = time.monotonic() - began
            picked = next((h for h in hits if h["id"] == chosen), None) or (hits[0] if len(hits) == 1 else None)
            if picked:
                values = service.read(cfg.workspace_id, picked["id"])
            log.info("TIMING compare_item %s: search %.2fs (%d hits), read %.2fs", number, searched, len(hits),
                     time.monotonic() - began - searched)
        except (FmApiError, AuthError) as exc:
            log.warning("Fusion Manage lookup failed: %s", exc)
            info.update(state=UNKNOWN, message=f"Could not read Fusion Manage: {exc}")
        else:
            if not hits:
                info.update(state=NEW)
            else:
                info["candidates"] = hits if len(hits) > 1 else []
                if picked:
                    info.update(state=FOUND, item_id=picked["id"])
                else:
                    info.update(state=MULTIPLE, message=f"{len(hits)} Fusion Manage items match {number}. Choose one.")
    if isinstance(properties, Future):   # still being read from the Data Model while Fusion Manage was asked
        properties = properties.result()
    result = {"fm": info,
              "rows": compare_properties(properties, summary, mappings, display_values(values) if values is not None else None, info["state"])}
    if with_values:
        result["values"] = values
    return result

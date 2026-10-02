"""Compare one design or component with its Fusion Manage item (shared by the panel and by publishing)."""

from typing import Any, Dict, List

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceConfig
from ..core.logging_setup import get_logger
from ..fm.client import FmApiError, FmClient
from ..fm.items import ItemService
from .property_compare import FOUND, MULTIPLE, NEW, UNKNOWN, compare_properties

log = get_logger("item_compare")


def compare_item(properties: List[Dict[str, str]], summary: Dict[str, Any], cfg: WorkspaceConfig,
                 fm: FmClient, chosen: str = "") -> Dict[str, Any]:
    """Compare the properties with Fusion Manage. Runs on a worker thread.

    The item is searched by item number in the Items workspace. When several
    items match, ``chosen`` (an item id the user picked) selects one; until then
    the state is ``multiple`` and ``candidates`` lists them.
    """
    mappings = [m for m in cfg.mappings if m.source and m.fm_field_id]
    number = str(summary.get("item_number") or summary.get("part_number") or "").strip()
    info: Dict[str, Any] = {"state": "unchecked", "message": "", "item_id": "", "item_number": number,
                            "candidates": []}
    fm_fields = None
    if not cfg.workspace_id:
        info["message"] = "Set the Items workspace ID in Settings to compare with Fusion Manage."
    elif not number:
        info["message"] = "This component has no item number to look up in Fusion Manage."
    else:
        try:
            service = ItemService(fm)
            hits = service.search(cfg.workspace_id, number)
            picked = next((h for h in hits if h["id"] == chosen), None) or (hits[0] if len(hits) == 1 else None)
            if picked:
                fm_fields = service.read(cfg.workspace_id, picked["id"])
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
    return {"fm": info,
            "rows": compare_properties(properties, summary, mappings, fm_fields, info["state"])}

"""What the Publish panel marks on the Bill of Materials it has read: the lines that cannot be published, and whether the design's number is shared.

A line without an item number, and every line below it, is skipped (``mark_skipped``) and never published. Fusion Manage's own Bill of Materials is not read
here: the structure viewer reads it once (``mbom_tree``) and compares it with this one. Everything here runs on a worker thread.
"""

from typing import Any, Dict, List

from ..core.logging_setup import get_logger
from ..config.workspace_models import WorkspaceConfig
from ..fm.client import FmClient
from ..fm.v3_search import WORKING, ItemFinder
from .bom_compare import SKIPPED, mark_skipped
from .item_number import item_number_of

log = get_logger("bom_levels")


def _with_skipped(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``rows`` with the skipped lines marked ``skipped``; every other line is left as it is."""
    return [{**row, "status": SKIPPED} if row.get("skip") else row for row in mark_skipped(rows)]


def _describe(rows: List[Dict[str, Any]]) -> str:
    """One line for the log: the rows indented by level, each with its item number and quantity."""
    return "; ".join(f"{'  ' * int(r['level'])}{r.get('item_number') or '(no item number)'} x{r.get('quantity', '')}" for r in rows)


def search_design(fm: FmClient, cfg: WorkspaceConfig, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The working versions of the Fusion Manage items with the design's number (none when there is nothing to look for). A publish changes
    the working version, so its Bill of Materials is the one compared with: the ids of its lines are the ones to change or remove. It needs
    only the summary, so it runs while the structure is still being read."""
    number = item_number_of(summary)
    if not (cfg and cfg.workspace_id and number):   # no workspace or no number: nothing to look for
        return []
    return ItemFinder(fm, WORKING).search(cfg.workspace_id, number)


def mark_design_bom(rows: List[Dict[str, Any]], summary: Dict[str, Any], hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The BOM rows read under the design, the unpublishable lines marked. ``hits`` are the Fusion Manage items found for the design's number
    (``search_design``): when several carry it, ``shared`` is set and the panel shows no structure until the number is fixed in Fusion Manage."""
    log.info("Design structure of %s: %s", item_number_of(summary) or "(no number)", _describe(rows) or "no components")
    if len(hits) > 1:
        return {"rows": rows, "shared": True}
    return {"rows": _with_skipped(rows), "shared": False}

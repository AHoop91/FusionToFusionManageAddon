"""Compare the Bill of Materials the Publish panel has read with Fusion Manage: the design's own lines, and the lines under an assembly.

The panel reads the first level of the design, then one assembly's lines at a time as it is opened, or the whole tree at once. Each read
is compared with Fusion Manage here: ``compare_design_bom`` for what was read under the design (a level, or the whole tree) and
``compare_level`` for the lines under one assembly. A line without an item number, and every line below it, is skipped (``mark_skipped``)
and never compared. Everything here runs on a worker thread.
"""

from typing import Any, Dict, List

from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch
from ..config.workspace_models import WorkspaceConfig
from ..fm.bom import WORKING_BIAS
from ..fm.client import FmClient
from ..fm.items import ItemService
from ..fm.search_query import WORKING
from .bom_compare import PARENT_SKIPPED, SKIPPED, UNCOMPARED, compare_bom, mark_skipped, read_and_compare_bom
from .item_compare import item_number_of

log = get_logger("bom_levels")


def _skipped_only(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``rows`` with the skipped lines marked and the rest left without a status (nothing to compare them with)."""
    return [{**row, "status": SKIPPED} if row.get("skip") else row for row in mark_skipped(rows)]


def _uncompared(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``rows`` with the skipped lines marked and the rest ``uncompared``: Fusion Manage has nothing to compare them with."""
    return [{**row, "status": SKIPPED if row.get("skip") else UNCOMPARED} for row in mark_skipped(rows)]


def search_design(fm: FmClient, cfg: WorkspaceConfig, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The working versions of the Fusion Manage items with the design's number (none when there is nothing to look for). A publish changes
    the working version, so its Bill of Materials is the one compared with: the ids of its lines are the ones to change or remove. It needs
    only the summary, so it runs while the structure is still being read."""
    number = item_number_of(summary)
    if not cfg or not cfg.workspace_id or not number:
        return []
    return ItemService(fm, WORKING).search(cfg.workspace_id, number)


def compare_design_bom(rows: List[Dict[str, Any]], summary: Dict[str, Any], cfg: WorkspaceConfig,
                       fm: FmClient, hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mark each BOM row read under the design against the Fusion Manage BOM of the open design.

    ``hits`` are the Fusion Manage items found for the design's number (``search_design``).
    One BOM call, deep enough for what was read, covers every assembly in it. Rows stay unchecked
    (no status) when the design is not compared. When several items carry the design's number,
    ``shared`` is set: nothing is compared until the number is fixed in Fusion Manage.
    ``fm_item_id`` is the Fusion Manage item compared with, empty when there is none (the Add Items picker needs it).
    """
    number = item_number_of(summary)
    log.info("Design structure of %s: %s", number or "(no number)", "; ".join(
        f"{'  ' * int(r['level'])}{r['item_number'] or '(no item number)'} x{r['quantity']}" for r in rows) or "no components")
    if not cfg or not cfg.workspace_id or not number:
        return {"rows": _skipped_only(rows), "shared": False}
    if not hits:
        # The design is not in Fusion Manage, so there is nothing to compare with. Each line is left unmarked, not asked about one by one (a
        # large design would be many requests): publishing looks each item up by its number then, and uses the one that is there.
        return {"rows": _uncompared(rows), "shared": False, "design_new": True}   # ``design_new``: the panel can say so at once, with no check to wait for
    if len(hits) > 1:
        return {"rows": rows, "shared": True}
    picked = hits[0]
    # A Fusion Manage or sign-in failure is not caught: the section fails and the panel offers Retry,
    # rather than caching a table that looks compared but is not.
    watch = Stopwatch()
    compared = read_and_compare_bom(rows, number, fm, cfg.workspace_id, picked["id"], WORKING_BIAS)
    log.debug("Read and compared the BOM of %s in %.2fs, %d rows", number, watch.lap(), len(rows))
    return {"rows": compared, "shared": False, "fm_item_id": picked["id"]}


def compare_level(rows: List[Dict[str, Any]], parent_number: str, parent_skipped: bool, compared: bool, cfg: WorkspaceConfig,
                  fm: FmClient) -> Dict[str, Any]:
    """The lines directly under one assembly, marked against the Fusion Manage BOM of that assembly.

    Nothing is asked of Fusion Manage when the assembly is skipped (its lines are too), when the design is not in Fusion Manage
    (``compared`` false: its lines are ``uncompared``), or when the assembly's item number matches several items (the lines are left
    uncompared rather than guessed at). An assembly Fusion Manage does not know has every line ``new``.
    """
    if parent_skipped:
        return {"rows": [{**row, "status": SKIPPED, "skip": PARENT_SKIPPED} for row in rows]}
    if not compared or not cfg or not cfg.workspace_id or not parent_number:
        return {"rows": _uncompared(rows)}
    hits = ItemService(fm, WORKING).search(cfg.workspace_id, parent_number)
    if len(hits) > 1:
        log.info("%s matches %d Fusion Manage items: its lines are not compared", parent_number, len(hits))
        return {"rows": _uncompared(rows)}
    marked = mark_skipped(rows)
    if not hits:   # Fusion Manage does not hold this assembly, so it holds none of its lines
        return {"rows": compare_bom(marked, parent_number, {})}
    return {"rows": read_and_compare_bom(marked, parent_number, fm, cfg.workspace_id, hits[0]["id"], WORKING_BIAS)}

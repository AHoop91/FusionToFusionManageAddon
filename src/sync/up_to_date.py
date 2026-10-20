"""Whether what Fusion Manage holds for the open design is up to date: the answers of the item panel's tabs.

Each check compares one thing the design says with the item shown and answers a ``state``: ``ok``, ``changes`` (with how many things differ
and their names), ``error`` (with a message) or ``unavailable`` (nothing to compare: the item is not the top of the open design). They use
the comparisons of the Publish panel, so the panel and publishing always agree. They read from Fusion Manage and the Data Model, so they run on
a worker thread.
"""

from typing import Any, Dict, List, NamedTuple

from ..config.workspace_models import WorkspaceConfig
from ..fm.client import FmClient
from ..fusion_mfg.design_reads import DesignReads
from ..fusion_mfg.graphql_client import MfgGraphQlClient
from .bom_compare import DIFFERING as BOM_DIFFERING, read_and_compare_bom
from .item_compare import item_number_of, read_and_compare
from .property_compare import FOUND, MISMATCH, NEW

OK, CHANGES, ERROR, UNAVAILABLE = "ok", "changes", "error", "unavailable"


class ShownItem(NamedTuple):
    """The item the panel shows, and the saved version of the open design it is compared with."""

    reads: DesignReads
    mfg: MfgGraphQlClient
    fm: FmClient
    cfg: WorkspaceConfig   # the Items workspace
    model_id: str
    time: str
    number: str   # the item number of the item shown
    item_id: str


def _verdict(differing: List[Dict[str, str]]) -> Dict[str, Any]:
    """``differing``: one ``{name, design, item}`` for each thing that differs, the design's value beside the item's ("" for none)."""
    return {"state": CHANGES if differing else OK, "differences": len(differing), "names": [d["name"] for d in differing], "details": differing}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _summary_of_item(shown: ShownItem) -> Dict[str, Any]:
    """The summary of the design, or an empty one when the item shown is not the design's own (a component below the top)."""
    summary = shown.reads.summary(shown.mfg, shown.model_id, shown.time)
    return summary if item_number_of(summary).lower() == shown.number.strip().lower() else {}


def check_properties(shown: ShownItem) -> Dict[str, Any]:
    """Whether the item's mapped fields hold what the design says; ``names`` are the fields that differ."""
    summary = _summary_of_item(shown)
    if not summary:
        return {"state": UNAVAILABLE}
    _, compared = read_and_compare(lambda: shown.reads.properties(shown.mfg, shown.model_id, shown.time, summary, shown.cfg.maps_physical()),
                                   summary, shown.cfg, shown.fm, known_id=shown.item_id)
    if compared["fm"]["state"] != FOUND:
        return {"state": ERROR, "message": compared["fm"]["message"] or "Fusion Manage could not be read."}
    return _verdict([{"name": r["name"], "design": _text(r.get("shown") or r.get("value")), "item": _text(r.get("fm_value"))}
                     for r in compared["rows"] if r["status"] in (MISMATCH, NEW)])


def check_bom(shown: ShownItem) -> Dict[str, Any]:
    """Whether every component of the design is under the same parent in the item's Bill of Materials, in the same quantity; ``names`` are
    the item numbers that are not. Lines only Fusion Manage has are not a difference."""
    summary = _summary_of_item(shown)
    if not summary:
        return {"state": UNAVAILABLE}
    rows = shown.reads.structure(shown.mfg, shown.model_id, shown.time, summary)
    compared = read_and_compare_bom(rows, shown.number, shown.fm, shown.cfg.workspace_id, shown.item_id)
    return _verdict([{"name": item_number_of(r) or _text(r.get("part_number")), "design": _text(r.get("quantity")),
                      "item": _text(r.get("fm_quantity"))}   # no quantity: it is not under that parent at all
                     for r in compared if r["status"] in BOM_DIFFERING])

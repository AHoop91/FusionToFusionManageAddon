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
from ..fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from .bom_compare import DIFFERING as BOM_DIFFERING, read_and_compare_bom
from .item_compare import read_and_compare
from .item_number import item_number_of
from .property_compare import FOUND, MISMATCH, NEW

OK, CHANGES, ERROR, UNAVAILABLE = "ok", "changes", "error", "unavailable"

# The statuses of a property row that publishing would change in the item.
PROPERTY_DIFFERING = (MISMATCH, NEW)


class ShownItem(NamedTuple):
    """The item the panel shows, and the saved version of the open design it is compared with."""

    reads: DesignReads            # the design's summary, properties and structure
    mfg: FusionGraphQlClient      # the Data Model client the design is read with
    fm: FmClient
    cfg: WorkspaceConfig          # the Items workspace
    model_id: str                 # the saved version of the open design...
    time: str                     # ... and when it was saved
    number: str                   # the item number of the item shown
    item_id: str                  # its Fusion Manage id


def _verdict(differing: List[Dict[str, str]]) -> Dict[str, Any]:
    """``differing``: one ``{name, design, item}`` for each thing that differs, the design's value beside the item's ("" for none)."""
    return {"state": CHANGES if differing else OK, "differences": len(differing), "names": [d["name"] for d in differing], "details": differing}


def _text(value: Any) -> str:
    """``value`` as text, "" for none."""
    return "" if value is None else str(value)


def _top_summary(shown: ShownItem) -> Dict[str, Any]:
    """The summary of the open design when the item shown is its top, else an empty one (a component below the top has nothing to compare)."""
    summary = shown.reads.summary(shown.mfg, shown.model_id, shown.time)
    return summary if item_number_of(summary).casefold() == shown.number.strip().casefold() else {}


def check_properties(shown: ShownItem) -> Dict[str, Any]:
    """Whether the item's mapped fields hold what the design says; ``names`` are the fields that differ."""
    summary = _top_summary(shown)
    if not summary:
        return {"state": UNAVAILABLE}

    def read_properties() -> List[Dict[str, str]]:
        return shown.reads.properties(shown.mfg, shown.model_id, shown.time, summary, shown.cfg.maps_physical())

    _, compared = read_and_compare(read_properties, summary, shown.cfg, shown.fm, known_id=shown.item_id)
    if compared["fm"]["state"] != FOUND:
        return {"state": ERROR, "message": compared["fm"]["message"] or "Fusion Manage could not be read."}
    return _verdict([{"name": r["name"], "design": _text(r.get("shown") or r.get("value")), "item": _text(r.get("fm_value"))}
                     for r in compared["rows"] if r["status"] in PROPERTY_DIFFERING])


def check_bom(shown: ShownItem) -> Dict[str, Any]:
    """Whether every component of the design is under the same parent in the item's Bill of Materials, in the same quantity; ``names`` are
    the item numbers that are not. Lines only Fusion Manage has are not a difference."""
    summary = _top_summary(shown)
    if not summary:
        return {"state": UNAVAILABLE}
    rows = shown.reads.structure(shown.mfg, shown.model_id, shown.time, summary)
    compared = read_and_compare_bom(rows, shown.number, shown.fm, shown.cfg.workspace_id, shown.item_id)
    # A differing line has an item number (one without is skipped). Its item quantity is "" when it is not under that parent at all.
    return _verdict([{"name": item_number_of(r), "design": _text(r.get("quantity")), "item": _text(r.get("fm_quantity"))}
                     for r in compared if r["status"] in BOM_DIFFERING])

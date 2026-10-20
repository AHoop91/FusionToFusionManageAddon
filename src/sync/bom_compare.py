"""Compare the design's BOM rows with the Fusion Manage BOM.

Each row gets a status: ``new`` (not under that parent in Fusion Manage yet),
``changed`` (quantity differs) or ``match``. Fusion Manage extends the design
BOM (oil, panels and other manufacturing lines), so lines only Fusion Manage has are
``extra`` rows, never deletions. An extra sits next to a ``new`` row of the same
parent when there is one, and the two carry each other's item number in ``pair``:
the item number differs at that position, which may be a replaced item, so the user
decides. Extras without a partner go after the parent's other children. Parents that
Fusion Manage does not know yet have every child ``new``; a design that is not in Fusion Manage at all has its lines ``uncompared``.
"""

from typing import Any, Dict, List, Set

from ..fm.bom import BomService
from ..fm.client import FmClient
from .item_compare import item_number_of

NEW, CHANGED, MATCH, EXTRA = "new", "changed", "match", "extra"
UNCOMPARED = "uncompared"   # the design is not in Fusion Manage at all: its lines are not compared, and not asked about one by one
DIFFERING = (NEW, CHANGED)   # the design's lines that Fusion Manage lacks under that parent or holds with another quantity; ``extra`` lines only Fusion Manage has are not a difference


def _key(number: str) -> str:
    return number.strip().casefold()


def _same_quantity(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return a.strip() == b.strip()


def compare_bom(rows: List[Dict[str, Any]], root_number: str,
                fm_bom: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """``rows`` (tree order, ``level`` 0 = direct child of the root) with a ``status`` each."""
    # Per parent, the Fusion Manage lines in order. An item number can appear on several lines.
    fm_lines = {_key(parent): list(kids) for parent, kids in fm_bom.items()}
    out: List[Dict[str, Any]] = []
    # One frame per open parent: its item number, which of its Fusion Manage lines the design has used, and its new rows.
    stack: List[Dict[str, Any]] = [{"number": root_number, "used": set(), "new": []}]

    def close() -> None:
        """Finish the innermost parent: add the Fusion Manage lines the design does not have."""
        frame = stack.pop()
        used: Set[int] = frame["used"]
        extras = [line for i, line in enumerate(fm_lines.get(_key(frame["number"])) or []) if i not in used]

        def extra(line: Dict[str, str], pair: str = "") -> Dict[str, Any]:
            return {"level": len(stack), "id": "", "item_number": line["number"], "sequence": line.get("sequence", ""),
                    "name": line.get("name", ""), "part_number": line["number"], "description": "",
                    "quantity": line["quantity"], "status": EXTRA, "pair": pair, "edge_id": line.get("edge_id", "")}

        pairs = list(zip(frame["new"], extras))
        for index, line in reversed(pairs):   # last first, so earlier positions stay valid
            out[index]["pair"] = line["number"]
            out.insert(index, extra(line, item_number_of(out[index])))
        out.extend(extra(line) for line in extras[len(pairs):])

    for row in rows:
        level = int(row["level"])
        while len(stack) > level + 1:
            close()
        frame = stack[-1]
        # Each design line takes the first unused Fusion Manage line with its item number, so repeats pair one to one.
        line = None
        for i, candidate in enumerate(fm_lines.get(_key(frame["number"])) or []):
            if i not in frame["used"] and _key(candidate["number"]) == _key(item_number_of(row)):
                frame["used"].add(i)
                line = candidate
                break
        if line is None:
            status = NEW
        elif _same_quantity(str(row.get("quantity", "")), line["quantity"]):
            status = MATCH
        else:
            status = CHANGED
        if status == NEW:
            frame["new"].append(len(out))
        out.append({**row, "status": status, "fm_quantity": line["quantity"] if line else "",
                    "fm_edge_id": line.get("edge_id", "") if line else ""})
        stack.append({"number": item_number_of(row), "used": set(), "new": []})
    while stack:
        close()
    return out


def read_and_compare_bom(rows: List[Dict[str, Any]], root_number: str, fm: FmClient, workspace_id: str, item_id: str) -> List[Dict[str, Any]]:
    """``compare_bom`` of the design's ``rows`` with the Fusion Manage BOM of the item ``item_id``, read deep enough for the whole tree in one
    call. Runs on a worker thread; the publish panel and the item panel's up-to-date check both use it."""
    depth = max([int(r["level"]) for r in rows] + [0]) + 1
    return compare_bom(rows, root_number, BomService(fm).read(workspace_id, item_id, depth))

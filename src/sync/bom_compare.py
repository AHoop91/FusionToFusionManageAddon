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
SKIPPED = "skipped"   # no item number: not in the Components workspace, so no item is created; neither is anything below it
DIFFERING = (NEW, CHANGED)   # the design's lines that Fusion Manage lacks under that parent or holds with another quantity; ``extra`` lines only Fusion Manage has are not a difference

NO_NUMBER = "no_number"   # why a line is skipped (the panel words it): it has no item number
PARENT_SKIPPED = "parent"   # ... or a line above it has none, so it has nothing to join in the Fusion Manage BOM


def _key(number: str) -> str:
    return number.strip().casefold()


def mark_skipped(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``rows`` (tree order) with a ``skip`` reason on each line that is not published: one without an item number, and
    every line below it. Other lines are left as they are."""
    out: List[Dict[str, Any]] = []
    below = None   # level of the skipped line whose lines are being passed
    for row in rows:
        level = int(row["level"])
        if below is not None and level > below:
            out.append({**row, "skip": PARENT_SKIPPED})
            continue
        below = None
        if not item_number_of(row):
            below = level
            out.append({**row, "skip": NO_NUMBER})
        else:
            out.append(row)
    return out


def _same_quantity(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return a.strip() == b.strip()


def _position(sequence: Any) -> str:
    """A line's BOM position as text ("" when it has none), so the design's 11 and Fusion Manage's "11" are the same."""
    text = str(sequence or "").strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return "" if number == 0 else str(int(number)) if number == int(number) else text


def _pair_by_position(new: List[Any], extras: List[Any]) -> List[Any]:
    """``[(index of a new design line, index of a Fusion Manage-only line)]``: a pair is a design line and a Fusion Manage line at the same BOM
    position under one parent, which may be a replaced item. A line at a position the other side does not use is not a replacement (a line
    removed in Fusion Manage at 11 and oil added at 12), so it is left unpaired. Lines with no position on either side pair in order.
    ``new`` and ``extras`` are ``(index, sequence)`` in order."""
    pairs: List[Any] = []
    free = list(extras)
    unplaced: List[Any] = []
    for index, sequence in new:
        position = _position(sequence)
        match = next((e for e in free if position and _position(e[1]) == position), None) if position else None
        if match is not None:
            free.remove(match)
            pairs.append((index, match[0]))
        elif not position:
            unplaced.append(index)
    pairs.extend(zip(unplaced, [e[0] for e in free if not _position(e[1])]))
    return pairs


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

        pairs = _pair_by_position([(index, out[index].get("sequence")) for index in frame["new"]],
                                  [(n, line.get("sequence")) for n, line in enumerate(extras)])
        for index, n in sorted(pairs, reverse=True):   # last first, so earlier positions stay valid
            out[index]["pair"] = extras[n]["number"]
            out.insert(index, extra(extras[n], item_number_of(out[index])))
        paired = {n for _, n in pairs}
        out.extend(extra(line) for n, line in enumerate(extras) if n not in paired)

    for row in mark_skipped(rows):
        if row.get("skip"):   # not compared, and it takes no Fusion Manage line
            out.append({**row, "status": SKIPPED})
            continue
        level = int(row["level"])
        while len(stack) > level + 1:
            close()
        frame = stack[-1]
        # Each design line takes an unused Fusion Manage line with its item number, so repeats pair one to one. Where two lines carry the number
        # (two items share it), the one named like the design line is taken, else the first.
        line = None
        free = [(i, c) for i, c in enumerate(fm_lines.get(_key(frame["number"])) or [])
                if i not in frame["used"] and _key(c["number"]) == _key(item_number_of(row))]
        if free:
            name = str(row.get("name") or row.get("description") or "").strip().lower()
            index, line = next(((i, c) for i, c in free if name and str(c.get("name", "")).strip().lower() == name), free[0])
            frame["used"].add(index)
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

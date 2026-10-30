"""Compare the design's BOM rows with the Fusion Manage BOM.

Each row gets a status: ``new`` (not under that parent in Fusion Manage yet), ``changed`` (quantity differs) or ``match``.
Fusion Manage extends the design BOM (oil, panels and other manufacturing lines), so lines only Fusion Manage has are ``extra``
rows, never deletions. An extra sits next to a ``new`` row of the same parent when there is one, and the two carry each other's
item number in ``pair``: the item number differs at that position, which may be a replaced item, so the user decides. Extras
without a partner go after the parent's other children. Parents that Fusion Manage does not know yet have every child ``new``;
a design that is not in Fusion Manage at all has its lines ``uncompared``.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..fm.bom import WORKING_BIAS, BomService
from ..fm.client import FmClient
from .item_number import item_number_of

NEW, CHANGED, MATCH, EXTRA = "new", "changed", "match", "extra"
# The design is not in Fusion Manage at all: its lines are not compared, and not asked about one by one.
UNCOMPARED = "uncompared"
# No item number: not in the Components workspace, so no item is created; neither is anything below it.
SKIPPED = "skipped"
# The design's lines that Fusion Manage lacks under that parent or holds with another quantity.
# ``extra`` lines only Fusion Manage has are not a difference.
DIFFERING = (NEW, CHANGED)

# Why a line is skipped (the panel words it): it has no item number...
NO_NUMBER = "no_number"
# ... or a line above it has none, so it has nothing to join in the Fusion Manage BOM.
PARENT_SKIPPED = "parent"

Line = Dict[str, str]   # a Fusion Manage BOM line: number, name, quantity, sequence, edge_id (see ``fm.bom``)


def _key(text: Any) -> str:
    """``text`` as it is compared: item numbers and names that differ only in case or outer spaces are the same."""
    return str(text or "").strip().casefold()


def _number(text: str) -> Optional[float]:
    """``text`` as a finite number, or None when it is not one (``nan`` and ``inf`` are words here, not quantities)."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def mark_skipped(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``rows`` (tree order) with a ``skip`` reason on each line that is not published: one without an item number, and
    every line below it. Other lines are left as they are. Marking twice gives the same rows."""
    out: List[Dict[str, Any]] = []
    below: Optional[int] = None   # level of the skipped line whose lines are being passed
    for row in rows:
        level = int(row["level"])
        if below is not None and level > below:
            out.append({**row, "skip": PARENT_SKIPPED})
            continue
        below = None
        if item_number_of(row):
            out.append(row)
        else:
            below = level
            out.append({**row, "skip": NO_NUMBER})
    return out


def _same_quantity(a: Any, b: Any) -> bool:
    """Whether two quantities are equal: as numbers when both are ("2" and "2.0"), else as text."""
    a, b = str(a).strip(), str(b).strip()
    x, y = _number(a), _number(b)
    return x == y if x is not None and y is not None else a == b


def _position(sequence: Any) -> str:
    """A line's BOM position as text ("" when it has none), so the design's 11 and Fusion Manage's "11" are the same."""
    text = str(sequence or "").strip()
    number = _number(text)
    if number is None:
        return text
    if number == 0:
        return ""
    return str(int(number)) if number == int(number) else text


def _pair_by_position(new: List[Tuple[int, Any]], extras: List[Tuple[int, Any]]) -> List[Tuple[int, int]]:
    """``[(index of a new design line, index of a Fusion Manage-only line)]``: a pair is a design line and a Fusion Manage line at the same BOM
    position under one parent, which may be a replaced item. A line at a position the other side does not use is not a replacement (a line
    removed in Fusion Manage at 11 and oil added at 12), so it is left unpaired. Lines with no position on either side pair in order.
    ``new`` and ``extras`` are ``(index, sequence)`` in order."""
    pairs: List[Tuple[int, int]] = []
    free = list(extras)
    unplaced: List[int] = []
    for index, sequence in new:
        position = _position(sequence)
        if not position:
            unplaced.append(index)
            continue
        match = next((e for e in free if _position(e[1]) == position), None)
        if match is not None:
            free.remove(match)
            pairs.append((index, match[0]))
    pairs.extend(zip(unplaced, [n for n, sequence in free if not _position(sequence)]))
    return pairs


@dataclass
class _Parent:
    """A parent whose children are being read: its item number, which of its Fusion Manage lines the design has used, and
    where its ``new`` rows are in the output."""

    number: str
    used: Set[int] = field(default_factory=set)
    new: List[int] = field(default_factory=list)


def _extra_row(line: Line, level: int, pair: str = "") -> Dict[str, Any]:
    """The row for a Fusion Manage line the design does not have. ``pair`` is the item number of the design line it sits next to."""
    number = line.get("number", "")
    return {"level": level, "id": "", "item_number": number, "sequence": line.get("sequence", ""), "name": line.get("name", ""),
            "part_number": number, "description": "", "quantity": line.get("quantity", ""), "status": EXTRA, "pair": pair,
            "edge_id": line.get("edge_id", "")}


def _take_line(lines: List[Line], parent: _Parent, row: Dict[str, Any]) -> Optional[Tuple[int, Line]]:
    """``(index, line)``: the unused Fusion Manage line of ``parent`` the design ``row`` stands for, or None when it has none, so repeats
    pair one to one. Where two lines carry the item number (two items share it), the one named like the design line is taken, else the first."""
    number = _key(item_number_of(row))
    free = [(i, line) for i, line in enumerate(lines) if i not in parent.used and _key(line.get("number")) == number]
    if not free:
        return None
    name = _key(row.get("name") or row.get("description"))
    return next(((i, line) for i, line in free if name and _key(line.get("name")) == name), free[0])


def _close_parent(out: List[Dict[str, Any]], parent: _Parent, level: int, lines: List[Line]) -> None:
    """Finish ``parent`` (its children are at ``level``): add to ``out`` the Fusion Manage ``lines`` the design does not have."""
    extras = [line for i, line in enumerate(lines) if i not in parent.used]
    pairs = _pair_by_position([(index, out[index].get("sequence")) for index in parent.new],
                              [(n, line.get("sequence")) for n, line in enumerate(extras)])
    for index, n in sorted(pairs, reverse=True):   # last first, so earlier positions stay valid
        out[index]["pair"] = extras[n].get("number", "")
        out.insert(index, _extra_row(extras[n], level, item_number_of(out[index])))
    paired = {n for _, n in pairs}
    out.extend(_extra_row(line, level) for n, line in enumerate(extras) if n not in paired)


def compare_bom(rows: List[Dict[str, Any]], root_number: str, fm_bom: Dict[str, List[Line]]) -> List[Dict[str, Any]]:
    """``rows`` (tree order, ``level`` 0 = direct child of the root) with a ``status`` each. A row more than one level below the one
    before it is read as that row's child."""
    # Per parent, the Fusion Manage lines in order. An item number can appear on several lines.
    fm_lines = {_key(parent): kids for parent, kids in fm_bom.items()}
    out: List[Dict[str, Any]] = []
    stack: List[_Parent] = [_Parent(root_number)]   # one per open parent

    def close() -> None:
        parent = stack.pop()
        _close_parent(out, parent, len(stack), fm_lines.get(_key(parent.number), []))

    for row in mark_skipped(rows):
        if row.get("skip"):   # not compared, and it takes no Fusion Manage line
            out.append({**row, "status": SKIPPED})
            continue
        level = min(int(row["level"]), len(stack) - 1)
        while len(stack) > level + 1:
            close()
        parent = stack[-1]
        taken = _take_line(fm_lines.get(_key(parent.number), []), parent, row)
        line: Line = {}
        if taken is None:
            status = NEW
            parent.new.append(len(out))
        else:
            index, line = taken
            parent.used.add(index)
            status = MATCH if _same_quantity(row.get("quantity", ""), line.get("quantity", "")) else CHANGED
        out.append({**row, "status": status, "fm_quantity": line.get("quantity", ""), "fm_edge_id": line.get("edge_id", "")})
        stack.append(_Parent(item_number_of(row)))
    while stack:
        close()
    return out


def read_and_compare_bom(rows: List[Dict[str, Any]], root_number: str, fm: FmClient, workspace_id: str, item_id: str,
                         bias: str = WORKING_BIAS) -> List[Dict[str, Any]]:
    """``compare_bom`` of the design's ``rows`` with the Fusion Manage BOM of the item ``item_id``, read deep enough for the whole tree in one
    call, with the revision of each line ``bias`` names (see ``BomService``). Runs on a worker thread; the publish panel and the item panel's
    up-to-date check both use it."""
    depth = max([int(r["level"]) for r in rows] + [0]) + 1
    return compare_bom(rows, root_number, BomService(fm, bias).read(workspace_id, item_id, depth))

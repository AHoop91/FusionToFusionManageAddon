"""Compare the design's BOM rows with the Fusion Manage BOM.

Each row gets a status: ``new`` (not under that parent in Fusion Manage yet),
``changed`` (quantity differs) or ``match``. Lines that only Fusion Manage has
are added as ``removed`` rows, each next to a ``new`` row of the same parent when
there is one (so a replaced item sits beside its replacement), else after the
parent's other children. Parents that
Fusion Manage does not know yet have every child ``new``.
"""

from typing import Any, Dict, List, Set

NEW, CHANGED, MATCH, REMOVED = "new", "changed", "match", "removed"


def _key(number: str) -> str:
    return number.strip().casefold()


def _same_quantity(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return a.strip() == b.strip()


def _number(row: Dict[str, Any]) -> str:
    return str(row.get("item_number") or row.get("part_number") or "")


def compare_bom(rows: List[Dict[str, Any]], root_number: str,
                fm_bom: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """``rows`` (tree order, ``level`` 0 = direct child of the root) with a ``status`` each."""
    fm_lines = {_key(parent): {_key(c["number"]): c for c in kids} for parent, kids in fm_bom.items()}
    out: List[Dict[str, Any]] = []
    # One frame per open parent: its item number and the child numbers the design has under it.
    stack: List[Dict[str, Any]] = [{"number": root_number, "seen": set(), "new": []}]

    def close() -> None:
        """Finish the innermost parent: add the Fusion Manage lines the design does not have."""
        frame = stack.pop()
        seen: Set[str] = frame["seen"]
        gone = [line for key, line in (fm_lines.get(_key(frame["number"])) or {}).items() if key not in seen]

        def removed(line: Dict[str, str]) -> Dict[str, Any]:
            return {"level": len(stack), "id": "", "item_number": line["number"], "sequence": line.get("sequence", ""),
                    "name": line.get("name", ""), "part_number": line["number"], "description": "",
                    "quantity": line["quantity"], "status": REMOVED}

        pairs = list(zip(frame["new"], gone))
        for index, line in reversed(pairs):   # last first, so earlier positions stay valid
            out.insert(index, removed(line))
        out.extend(removed(line) for line in gone[len(pairs):])

    for row in rows:
        level = int(row["level"])
        while len(stack) > level + 1:
            close()
        frame = stack[-1]
        frame["seen"].add(_key(_number(row)))
        known = fm_lines.get(_key(frame["number"]))
        line = (known or {}).get(_key(_number(row)))
        if line is None:
            status = NEW
        elif _same_quantity(str(row.get("quantity", "")), line["quantity"]):
            status = MATCH
        else:
            status = CHANGED
        if status == NEW:
            frame["new"].append(len(out))
        out.append({**row, "status": status, "fm_quantity": line["quantity"] if line else ""})
        stack.append({"number": _number(row), "seen": set(), "new": []})
    while stack:
        close()
    return out

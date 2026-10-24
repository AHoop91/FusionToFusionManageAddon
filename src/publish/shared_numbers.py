"""Item numbers that more than one component of a publish carry.

Components with one item number would all find, and write to, the same Fusion Manage item, each overwriting the others' values. The panel
leaves such lines out of the job (``bom-model.js``, ``markShared``); this is the run's own check, so a job that was built some other way
cannot publish them either.
"""

from typing import Any, Dict, List

from ..sync.item_compare import item_number_of
from .read_ahead import component_id_of


def shared_numbers(items: List[Dict[str, Any]], summary: Dict[str, Any]) -> Dict[str, List[str]]:
    """``{item number (trimmed, lower case): the components that carry it}`` for each number held by more than one component.

    A component that is on several lines of the design is one component: it is told apart by its Data Model id."""
    holders: Dict[str, Dict[str, str]] = {}
    for item in items:
        number = item_number_of(item).lower()
        if number:
            who = str(item.get("name") or item.get("description") or "").strip() or "a component without a name"
            holders.setdefault(number, {})[component_id_of(item, summary) or f"line {id(item)}"] = who
    return {number: list(who.values()) for number, who in holders.items() if len(who) > 1}


def shared_reason(number: str, holders: List[str]) -> str:
    """What a run says of an item that is left out because its number is shared."""
    return f"Skipped: item number {number} is shared by {len(holders)} components ({', '.join(holders)}). Give each its own item number in Fusion."

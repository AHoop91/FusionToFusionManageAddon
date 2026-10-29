"""Item numbers that more than one component of a publish carry.

Components with one item number would all find, and write to, the same Fusion Manage item, each overwriting the others' values. The panel
leaves such lines out of the job (``bom-model.js``, ``markShared``); this is the run's own check, so a job that was built some other way
cannot publish them either. The two apply one rule, so a change to it is made in both.
"""

from typing import Any, Dict, List

from ..sync.item_number import item_number_of
from .read_ahead import component_id_of

UNNAMED = "a component without a name"


def shared_key(number: str) -> str:
    """An item number as ``shared_numbers`` keys it (trimmed, lower case): how a caller looks a number up in its answer."""
    return number.strip().lower()


def shared_numbers(items: List[Dict[str, Any]], summary: Dict[str, Any]) -> Dict[str, List[str]]:
    """``{item number key: the components that carry it}`` for each number held by more than one component (see ``shared_key``).

    A component that is on several lines of the design is one component: it is told apart by its Data Model id. A line with no id is told
    apart by its place in the list, as the panel does."""
    holders: Dict[str, Dict[str, str]] = {}   # number key -> {component id -> its name}
    for at, item in enumerate(items):
        number = shared_key(item_number_of(item))
        if number:
            who = str(item.get("name") or item.get("description") or "").strip() or UNNAMED
            holders.setdefault(number, {})[component_id_of(item, summary) or f"line {at}"] = who
    return {number: list(who.values()) for number, who in holders.items() if len(who) > 1}


def shared_reason(number: str, holders: List[str]) -> str:
    """What a run says of an item that is left out because its number is shared: the number, and the components that carry it."""
    return f"Skipped: item number {number} is shared by {len(holders)} components ({', '.join(holders)}). Give each its own item number in Fusion."

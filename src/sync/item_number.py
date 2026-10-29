"""The item number a design or component is looked up by in Fusion Manage."""

from typing import Any, Mapping


def item_number_of(summary: Mapping[str, Any]) -> str:
    """The number to look a design or component up by in Fusion Manage: its item number, without outer spaces.

    It is never the part number: a component without an item number is not published, so the result is "" and callers skip it.
    """
    return str(summary.get("item_number") or "").strip()

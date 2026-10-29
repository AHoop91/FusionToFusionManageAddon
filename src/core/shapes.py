"""Reading the JSON a service sends without trusting its shape.

An answer of an unexpected shape reads as "nothing there", not as an error: each helper gives an empty value where the shape is wrong.
"""

from typing import Any, Dict, List


def as_dict(value: Any) -> Dict[str, Any]:
    """``value`` when it is an object, else an empty one."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> List[Any]:
    """``value`` when it is a list, else an empty one."""
    return value if isinstance(value, list) else []


def dict_rows(value: Any) -> List[Dict[str, Any]]:
    """The objects in ``value`` when it is a list (anything else in it is left out), else an empty list."""
    return [row for row in as_list(value) if isinstance(row, dict)]


def rows_in(data: Any, key: str) -> List[Dict[str, Any]]:
    """The objects of an answer that is either the list itself or an object holding it under ``key`` (Fusion Manage answers some lists
    either way)."""
    return dict_rows(data.get(key) if isinstance(data, dict) else data)


def whole(value: Any) -> int:
    """``value`` as a whole number; 0 when it is missing or not a number (a count or an order the service sent as it pleased)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def dig(value: Any, *keys: str) -> Any:
    """What lies at the path ``keys`` in ``value`` (``dig(data, "hub", "members")`` is ``data["hub"]["members"]``), or None when any step
    of it is missing or not an object."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value

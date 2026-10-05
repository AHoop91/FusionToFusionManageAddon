"""The ``{{kind:argument}}`` markers in the request files, and how they are filled in when the files are sent.

The files are written before anything exists in Fusion Manage, so what only Fusion Manage knows is a marker:
``{{item:<number>}}`` an item's id, ``{{version:<number>}}`` its revision, ``{{tenant}}`` the tenant code of the urns,
``{{edge:<parent>><number>@<sequence>}}`` a BOM line's id. Pure functions, no I/O.
"""

import re
from typing import Any, Dict, List, Set, Tuple

_MARKER = re.compile(r"\{\{([a-z]+)(?::([^{}]*))?\}\}")

Key = Tuple[str, str]   # (kind, argument); item numbers compare without regard to case


class Unresolved(Exception):
    """Markers that have no value; ``keys`` lists them."""

    def __init__(self, keys: List[Key]) -> None:
        self.keys = keys
        super().__init__("No value for " + ", ".join("{{%s%s}}" % (k, ":" + a if a else "") for k, a in keys))


def key_of(kind: str, argument: str = "") -> Key:
    return (kind, argument.strip().casefold() if kind in ("item", "version") else argument)


def markers(node: Any) -> Set[Key]:
    """Every marker anywhere in a request (url, body, nested lists and objects)."""
    found: Set[Key] = set()
    if isinstance(node, str):
        found.update(key_of(m.group(1), m.group(2) or "") for m in _MARKER.finditer(node))
    elif isinstance(node, dict):
        for value in node.values():
            found |= markers(value)
    elif isinstance(node, list):
        for value in node:
            found |= markers(value)
    return found


def resolve(node: Any, values: Dict[Key, str]) -> Any:
    """``node`` with every marker replaced by its value; ``Unresolved`` if any has none."""
    missing = sorted(k for k in markers(node) if k not in values)
    if missing:
        raise Unresolved(missing)

    def fill(text: str) -> str:
        return _MARKER.sub(lambda m: values[key_of(m.group(1), m.group(2) or "")], text)

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return fill(value)
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(node)

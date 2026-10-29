"""The ``{{kind:argument}}`` markers in the request files, and how they are filled in when the files are sent.

The files are written before anything exists in Fusion Manage, so what only Fusion Manage knows is a marker:
``{{item:<number>}}`` an item's id, ``{{version:<number>}}`` its revision, ``{{tenant}}`` the tenant code of the urns,
``{{edge:<parent>><number>@<sequence>}}`` a BOM line's id. Pure functions, no I/O.

A request is JSON (text, lists and objects): markers are found in its text values, not in the names of an object's fields.
"""

import re
from typing import Any, Callable, Dict, Iterator, List, Set, Tuple

_KIND = r"[a-z]+"
_ARGUMENT = r"[^{}]*"   # so a marker ends at the first closing braces, and ``{{`` inside an argument is not one
_MARKER = re.compile(r"\{\{(" + _KIND + r")(?::(" + _ARGUMENT + r"))?\}\}")
ITEM, VERSION, EDGE, TENANT = "item", "version", "edge", "tenant"   # the kinds of marker there are
CASELESS = (ITEM, VERSION)   # kinds whose argument is an item number: ``PN-1`` and ``pn-1`` are the same item

Key = Tuple[str, str]   # (kind, argument), the argument made as ``key_of`` makes it


class Unresolved(Exception):
    """Markers that have no value; ``keys`` lists them."""

    def __init__(self, keys: List[Key]) -> None:
        self.keys = keys
        super().__init__("No value for " + ", ".join(marker(k, a) for k, a in keys))


def marker(kind: str, argument: str = "") -> str:
    """The marker text for ``kind`` and ``argument``, as ``markers`` and ``resolve`` read it.

    Raises ``ValueError`` for what could not be read back: a kind that is not lower case letters, or an argument with a brace in it. Such a
    marker would be left in the request as it is, and sent."""
    if not re.fullmatch(_KIND, kind):
        raise ValueError(f"A marker's kind is lower case letters, not {kind!r}.")
    if "{" in argument or "}" in argument:
        raise ValueError(f"A marker's argument has no braces in it: {argument!r}.")
    return "{{%s%s}}" % (kind, ":" + argument if argument else "")


def key_of(kind: str, argument: str = "") -> Key:
    """The key a marker is looked up by: the kind, and the argument (an item number without its spaces or case)."""
    return (kind, argument.strip().casefold() if kind in CASELESS else argument)


def _key(found: "re.Match[str]") -> Key:
    return key_of(found.group(1), found.group(2) or "")


def _texts(node: Any) -> Iterator[str]:
    """The text values anywhere in a request: its url, its body and what the body holds."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _texts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _texts(value)


def _mapped(node: Any, change: Callable[[str], str]) -> Any:
    """A copy of a request with each of its text values changed by ``change``."""
    if isinstance(node, str):
        return change(node)
    if isinstance(node, dict):
        return {name: _mapped(value, change) for name, value in node.items()}
    if isinstance(node, list):
        return [_mapped(value, change) for value in node]
    return node


def markers(node: Any) -> Set[Key]:
    """Every marker anywhere in a request (url, body, nested lists and objects)."""
    return {_key(found) for text in _texts(node) for found in _MARKER.finditer(text)}


def resolve(node: Any, values: Dict[Key, str]) -> Any:
    """``node`` with every marker replaced by its value (a value is put in as it is: it is not read for markers); ``Unresolved`` if any has none."""
    missing = sorted(key for key in markers(node) if key not in values)
    if missing:
        raise Unresolved(missing)
    return _mapped(node, lambda text: _MARKER.sub(lambda found: values[_key(found)], text))

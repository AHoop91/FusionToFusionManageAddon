"""The query of a Fusion Manage search (``/api/v3/search-results?query=...``) for the Add Items picker.

The picker offers free text (matched against the item descriptor) and filter groups. A group holds rows
``field = value`` joined by AND or OR; groups are joined by AND or OR too. Whatever the user builds, the whole (in brackets) is
ANDed with the Items workspace so an OR can never reach other workspaces.

The query is returned as readable text (``ITEM_DETAILS:COUNTRY=United States AND ...``); ``encode`` turns it into
what goes after ``query=``.
"""

import re
from typing import Any, List
from urllib.parse import quote_plus

_UNSAFE = re.compile(r"[`():<>=\\/\]\[\{\}\"]")   # characters that mean something to the search syntax
_FIELD = re.compile(r"[^A-Z0-9_]")
_PREFIX = "ITEM_DETAILS:"


def clean_value(raw: Any) -> str:
    """A value with the characters the search syntax reads as operators removed."""
    return _UNSAFE.sub("", str(raw or "")).strip()


def term(value: str) -> str:
    """A cleaned value as the search reads it: one with spaces in quotes (``COUNTRY="United States"``), else as it is."""
    return f'"{value}"' if re.search(r"\s", value) else value


def field_id(raw: Any) -> str:
    """A field id as the search wants it: upper case, no ``ITEM_DETAILS:`` prefix, nothing but letters, digits and ``_``."""
    text = str(raw or "").strip().upper()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX):]
    return _FIELD.sub("", text)


def _join(raw: Any) -> str:
    return "OR" if str(raw or "").upper() == "OR" else "AND"


def _chain(pieces: List[str], joins: List[str]) -> str:
    """``pieces`` joined as ``joins`` say (``joins[i]`` connects ``pieces[i]`` to the next), in brackets when there is more than one."""
    text = pieces[0]
    for join, piece in zip(joins, pieces[1:]):
        text += f" {join} {piece}"
    return f"({text})" if len(pieces) > 1 else text


def _group_clause(group: Any) -> str:
    """``(A=1 OR B=2)`` for one group, or an empty string when none of its rows is filled in."""
    pieces: List[str] = []
    joins: List[str] = []
    rows = group.get("filters") if isinstance(group, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        field, value = field_id(row.get("field")), clean_value(row.get("value"))
        if not field or not value:
            continue   # a row not filled in is no filter
        pieces.append(f"{_PREFIX}{field}={term(value)}")
        joins.append(_join(row.get("join")))
    return _chain(pieces, joins) if pieces else ""   # a row's join says how it connects to the next row


def build_query(workspace_id: str, text: str = "", groups: Any = None) -> str:
    """The full query for ``text`` and filter ``groups`` (``[{"join", "filters": [{"field", "value", "join"}]}]``) in a workspace."""
    clauses: List[str] = []
    typed = clean_value(text)
    if typed:
        clauses.append(term(typed))
    found: List[str] = []
    joins: List[str] = []
    for group in groups if isinstance(groups, list) else []:
        clause = _group_clause(group)
        if clause:
            found.append(clause)
            joins.append(_join(group.get("join")))
    if found:
        clauses.append(_chain(found, joins))
    scope = f"workspaceId={int(workspace_id)}"
    if not clauses:
        return scope
    # Everything the user typed is bracketed as one, so an OR in it can never reach past the workspace.
    return f"({' AND '.join(clauses)}) AND {scope}"


def encode(query: str) -> str:
    """``query`` as it goes after ``query=``: spaces as ``+``, ``=`` as ``%3D``, parentheses left as they are."""
    return quote_plus(query, safe="()")


LATEST, WORKING = 1, 3   # the search's ``revision`` filter: 1 the latest version of each item, 3 the working version
REVISIONS = (LATEST, WORKING)


def search_path(workspace_id: str, text: str, groups: Any, offset: int, limit: int, revision: int = LATEST) -> str:
    """The request path of one page of a search, oldest first (a stable order to page through).

    ``revision`` picks the versions listed: 1 the latest version of each item (a working one included), 3 the working version
    only. Items that are not revision controlled are listed in both."""
    revision = revision if revision in REVISIONS else LATEST
    query = encode(build_query(workspace_id, text, groups))
    return (f"/api/v3/search-results?limit={int(limit)}&offset={max(0, int(offset))}&query={query}"
            f"&revision={revision}&sort={quote_plus('createdOn asc')}")

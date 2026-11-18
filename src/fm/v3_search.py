"""Everything that searches Fusion Manage through the v3 search API (``GET /api/v3/search-results``), in one place.

The v3 search is a query string (``query=``) over the search index, scoped to one workspace. This module holds:

- the constants of the search (paths, page sizes, the ``revision`` filter),
- building the query and the request path (``build_query``, ``encode``, ``search_path``, ``page_path``),
- reading the rows of an answer (``item_id_of`` is in ``pages``; ``rows``, ``hits``, ``number_key`` are here),
- choosing among several hits (``resolve_hits``, ``ItemChoices``),
- the searches themselves: ``ItemFinder`` (by item number), ``ItemSearchService`` (the Add Items picker).

It cannot search the Grid tab of a workspace; ``v1_search`` does that. Finding the Components workspace record is in ``components``, which
builds its request with ``component_path``. Read ``dev/finding-items.md`` before adding a search.
"""

import re
import threading
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list, dict_rows, dig, whole
from .bom import ACCEPT, WORKING_BIAS, name_of, number_of
from .client import WORKSPACES, FmClient
from .items import collect_values
from .linkable import linkable_row
from .pages import DESCRIPTOR_KEYS, ITEM_ID, item_id_of

log = get_logger("fm.v3_search")

SEARCH_RESULTS = "/api/v3/search-results"
LATEST, WORKING = 1, 3   # the search's ``revision`` filter: 1 the latest version of each item, 3 the working version (2 is every revision)
REVISIONS = (LATEST, WORKING)
SORT = "createdOn asc"   # oldest first: a stable order to page through
SEARCH_LIMIT = 50        # most items listed for one item number (and records for one component)
FIND_PAGE = 50           # items one page of a search that carries the item details holds
PAGE_SIZE = 25           # rows the Add Items picker asks the search for at a time; it reads on until this many rows are visible
MEMBERS_DEPTH = 1        # levels of the Bill of Materials read for its members: the lines directly under the item
ITEMS_BULK = "application/vnd.autodesk.plm.items.bulk+json"   # asked of a search: each hit is the item with its fields, not only a link
_UNSAFE = re.compile(r"[`():<>=\\/\]\[\{\}\"]")   # characters that mean something to the search syntax
_FIELD = re.compile(r"[^A-Z0-9_]")
_PREFIX = "ITEM_DETAILS:"
_TRAILING_REVISION = re.compile(r"\[REV:([^\]]*)\]\s*$")   # the ``[REV:w]`` that ends a title
_REV_LABEL = re.compile(r"^\s*\[?\s*(?:REV:?)?\s*([^\]]*?)\s*\]?\s*$", re.IGNORECASE)

Hit = Dict[str, str]   # an item a search found: ``{"id", "descriptor"}`` (the panel takes it as it is, so it is a plain object)


# ---- Building the query -------------------------------------------------------------------------------------------------------------

def clean_value(raw: Any) -> str:
    """A value with the characters the search syntax reads as operators removed. A value of 0 is a value, not nothing."""
    return _UNSAFE.sub("", "" if raw is None else str(raw)).strip()


def term(value: str) -> str:
    """A cleaned value as the search reads it: one with spaces in quotes (``COUNTRY="United States"``), else as it is."""
    return f'"{value}"' if re.search(r"\s", value) else value


def field_id(raw: Any) -> str:
    """A field id as the search wants it: upper case, no ``ITEM_DETAILS:`` prefix, nothing but letters, digits and ``_``."""
    text = str(raw or "").strip().upper()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX):]
    return _FIELD.sub("", text)


def quoted(number: str) -> str:
    """``number`` as a quoted search term. A quote or backslash would end the term early, so they are left out."""
    return '"' + number.strip().replace('"', "").replace("\\", "") + '"'


def _join(raw: Any) -> str:
    """``OR`` when that is what was asked for, else ``AND``: nothing the page sends can put anything else into the query."""
    return "OR" if str(raw or "").upper() == "OR" else "AND"


def _chain(parts: List[Tuple[str, str]]) -> str:
    """``parts``, each a clause and how it joins to the next, as one clause: in brackets when there is more than one."""
    text = parts[0][0]
    for (_, join), (clause, _) in zip(parts, parts[1:]):
        text += f" {join} {clause}"
    return f"({text})" if len(parts) > 1 else text


def _group_clause(group: Any) -> str:
    """``(A=1 OR B=2)`` for one group, or an empty string when none of its rows is filled in."""
    parts: List[Tuple[str, str]] = []
    for row in dict_rows(dig(group, "filters")):
        field, value = field_id(row.get("field")), clean_value(row.get("value"))
        if field and value:   # a row not filled in is no filter
            parts.append((f"{_PREFIX}{field}={term(value)}", _join(row.get("join"))))
    return _chain(parts) if parts else ""


def build_query(workspace_id: str, text: str = "", groups: Any = None) -> str:
    """The full query for ``text`` and filter ``groups`` (``[{"join", "filters": [{"field", "value", "join"}]}]``) in a workspace.

    The picker offers free text (matched against the item descriptor) and groups of rows ``field = value`` joined by AND or OR; groups are
    joined by AND or OR too. The whole, in brackets, is ANDed with the workspace so an OR can never reach other workspaces.
    ``workspace_id`` must be a number (``ValueError`` otherwise): it is what keeps the query inside the workspace."""
    clauses: List[str] = []
    typed = clean_value(text)
    if typed:
        clauses.append(term(typed))
    groups_found = [(clause, _join(group.get("join"))) for group in dict_rows(groups) if (clause := _group_clause(group))]
    if groups_found:
        clauses.append(_chain(groups_found))
    scope = f"workspaceId={int(workspace_id)}"
    if not clauses:
        return scope
    # Everything the user typed is bracketed as one, so an OR in it can never reach past the workspace.
    return f"({' AND '.join(clauses)}) AND {scope}"


def encode(query: str) -> str:
    """``query`` as it goes after ``query=``: spaces as ``+``, ``=`` as ``%3D``, parentheses left as they are."""
    return quote_plus(query, safe="()")


def page_path(query: str, offset: int, limit: int, revision: int) -> str:
    """The request path of one page of a search for ``query`` (readable text, not yet encoded)."""
    return f"{SEARCH_RESULTS}?limit={limit}&offset={offset}&page={offset // limit + 1}&query={encode(query)}&revision={revision}"


def search_path(workspace_id: str, text: str, groups: Any, offset: int, limit: int, revision: int = LATEST) -> str:
    """The request path of one page of the picker's search, oldest first.

    ``revision`` picks the versions listed: 1 the latest version of each item (a working one included), 3 the working version
    only. Items that are not revision controlled are listed in both."""
    revision = revision if revision in REVISIONS else LATEST
    query = encode(build_query(workspace_id, text, groups))
    return f"{SEARCH_RESULTS}?limit={int(limit)}&offset={max(0, whole(offset))}&query={query}&revision={revision}&sort={quote_plus(SORT)}"


# ---- Reading the answer -------------------------------------------------------------------------------------------------------------

def rows(data: Any) -> List[Dict[str, Any]]:
    """The items of a search-results answer."""
    return dict_rows(dig(data, "items"))


def descriptor_of(row: Dict[str, Any], default: str = "") -> str:
    """The descriptor a search row names (``9410-306 - STEP``), else ``default``."""
    return str(next((row[key] for key in DESCRIPTOR_KEYS if row.get(key)), default))


def hits(data: Any) -> List[Hit]:
    """``{"id", "descriptor"}`` for each item of a search-results answer."""
    return [{"id": item_id, "descriptor": str(row.get("descriptor") or item_id)} for row in rows(data) if (item_id := item_id_of(row))]


def number_key(descriptor: str) -> str:
    """The item number of an item descriptor (``9410-306 - STEP`` is ``9410-306``), as it is compared: trimmed, in lower case."""
    return descriptor.split(" - ", 1)[0].strip().lower()


def _revision_label(raw: Any) -> str:
    """The revision letter alone: Fusion Manage may send ``W``, ``REV:W`` or ``[REV:W]``."""
    match = _REV_LABEL.match(str(raw or ""))
    return match.group(1) if match else str(raw or "")


def _version(row: Dict[str, Any], title: str) -> str:
    """The revision a search row is of: its own field, else the ``[REV:x]`` its title ends with."""
    ending = _TRAILING_REVISION.search(title)
    return _revision_label(row.get("version") or row.get("revision") or (ending.group(1) if ending else ""))


def parse_search(data: Any, workspace_id: str, parent_id: str) -> Dict[str, Any]:
    """``{"total", "raw", "items": [{"id", "link", "number", "name", "version", "linkable"}]}`` of a picker search answer.

    ``raw`` is how many rows the page held, to continue from. The parent item is left out of ``items`` (it cannot hold itself; there
    is none while the design is not in Fusion Manage), and ``total`` is as the search counted it, so it is one too high once the parent
    is among the matches. ``linkable`` is None while there is no parent: the publish writes the row once the parent exists. A search
    answer has no linkable-items row, so the row that adding an item to a BOM posts back is written from the ids, as Fusion Manage
    would answer it (the tenant is filled in when the request is sent, see ``placeholders``).
    """
    data = as_dict(data)
    items: List[Dict[str, Any]] = []
    for row in rows(data):
        item_id = item_id_of(row)
        if not item_id or item_id == str(parent_id):
            continue
        title = descriptor_of(row, item_id)
        items.append({"id": item_id, "link": f"{WORKSPACES}/{workspace_id}/items/{item_id}",
                      "number": number_of(title), "name": name_of(title) or title, "version": _version(row, title),
                      "linkable": linkable_row(workspace_id, parent_id, item_id) if parent_id else None})
    return {"total": whole(data.get("totalCount") or data.get("totalHits")), "raw": len(as_list(data.get("items"))), "items": items}


def parse_members(data: Any) -> Dict[str, List[str]]:
    """``{"ids", "numbers"}`` of the nodes of a bulk BOM answer."""
    ids: List[str] = []
    numbers: List[str] = []
    for node in dict_rows(dig(data, "nodes")):
        item = as_dict(node.get("item"))
        match = ITEM_ID.search(str(item.get("link") or ""))
        if match:
            ids.append(match.group(1))
        number = number_of(str(item.get("title") or ""))
        if number:
            numbers.append(number)
    return {"ids": ids, "numbers": numbers}


# ---- Choosing among several hits ---------------------------------------------------------------------------------------------------

def resolve_hits(hits: List[Hit], number: str, chosen: str = "") -> Tuple[Optional[Hit], List[Hit]]:
    """``(hit, competing)`` for the ``hits`` of a search for ``number``: the item to use, or None when the user has to choose.

    ``competing`` are the items that share the number: those whose descriptor starts with exactly ``number``, else every hit. Exactly one
    of them is used as it is. Several are a choice for the user: ``chosen`` (an item id picked earlier) settles it when it is one of them,
    else the hit is None. ``competing`` is empty when there are no hits.
    """
    wanted = number.strip().lower()
    exact = [hit for hit in hits if number_key(hit["descriptor"]) == wanted]
    competing = exact or list(hits)
    picked = next((hit for hit in competing if hit["id"] == chosen), None) if chosen else None
    if picked is None and len(competing) == 1:
        picked = competing[0]
    return picked, competing


class ItemChoices:
    """The item the user picked where several items share an item number, by workspace and number, for as long as the add-in runs.

    One store is shared by the Item panel and by the uploads that start from it, so they cannot disagree. Any thread may use it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chosen: Dict[Tuple[str, str], str] = {}

    @staticmethod
    def _key(workspace_id: str, number: str) -> Tuple[str, str]:
        return workspace_id, number.strip().lower()

    def set(self, workspace_id: str, number: str, item_id: str) -> None:
        """Remember ``item_id`` for the number; an empty id forgets the choice."""
        with self._lock:
            if item_id:
                self._chosen[self._key(workspace_id, number)] = item_id
            else:
                self._chosen.pop(self._key(workspace_id, number), None)

    def resolve(self, workspace_id: str, number: str, found: List[Hit]) -> Tuple[Optional[Hit], List[Hit]]:
        """``resolve_hits`` with the choice made for the number. A choice that is none of the hits any more is forgotten."""
        with self._lock:
            chosen = self._chosen.get(self._key(workspace_id, number), "")
            if chosen and not any(hit["id"] == chosen for hit in found):
                self._chosen.pop(self._key(workspace_id, number), None)
                chosen = ""
        return resolve_hits(found, number, chosen)


# ---- The searches -------------------------------------------------------------------------------------------------------------------

class ItemFinder:
    """Finds items of a workspace by item number through an ``FmClient``. Call from a worker thread; a failed search raises.

    ``revision`` is the version of each item that searches list: ``WORKING`` (the default) or ``LATEST``. The add-in
    works on the working version throughout: what a publish or an export changes, and what the panels show and compare, is the one
    version a change can reach (a released version cannot be changed)."""

    def __init__(self, client: FmClient, revision: int = WORKING) -> None:
        self._client, self._revision = client, revision

    def search(self, workspace_id: str, item_number: str) -> List[Hit]:
        """Items of the workspace whose descriptor matches ``item_number``, as ``{"id", "descriptor"}``."""
        if not item_number:
            return []
        query = f"itemDescriptor={quoted(item_number)} AND (workspaceId={workspace_id})"
        found = hits(self._client.get_json(page_path(query, 0, SEARCH_LIMIT, self._revision)))
        log.info("Item number %s matched %d item(s) in workspace %s", item_number, len(found), workspace_id)
        return found

    def find_many(self, workspace_id: str, numbers: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """The items of the workspace whose item number is one of ``numbers``, in one search that returns the item details too.

        By item number (trimmed, lower case), each with its hits as ``{"id", "descriptor", "values"}`` (``values`` as ``ItemService.read``
        gives them, empty when the answer carried no fields). A number the answer holds no hit for is left out: that is not "no such
        item", since this search may differ from the one by number alone, so the caller asks for it again on its own. Raises
        ``FmApiError`` when it fails."""
        wanted = {n.strip().lower() for n in numbers if n.strip()}
        if not wanted:
            return {}
        terms = " OR ".join(f"itemDescriptor={quoted(n)}" for n in numbers if n.strip())
        query = f"({terms}) AND (workspaceId={workspace_id})"
        found: Dict[str, List[Dict[str, Any]]] = {}
        offset = 0
        while True:
            data = self._client.get_json(page_path(query, offset, FIND_PAGE, self._revision), accept=ITEMS_BULK)
            page = rows(data)
            for row in page:
                descriptor = descriptor_of(row)
                item_id = item_id_of(row)
                if item_id and number_key(descriptor) in wanted:
                    found.setdefault(number_key(descriptor), []).append({"id": item_id, "descriptor": descriptor, "values": collect_values(row)})
            offset += FIND_PAGE
            if not page or offset >= whole(dig(data, "totalCount")):
                break
        log.info("Searched %d item number(s) in workspace %s: %d found", len(wanted), workspace_id, len(found))
        return found


class ItemSearchService:
    """Searches the Items workspace for items to add to a Fusion Manage item's Bill of Materials (the Add Items picker)."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def page(self, workspace_id: str, parent_id: str, text: str, groups: Any, offset: int, revision: int = LATEST) -> Dict[str, Any]:
        """One page of the items matching ``text`` and the filter ``groups``, from ``offset``, oldest first; ``revision`` is as in ``search_path``.

        The answer is that of ``parse_search`` and ``limit``, how many rows a page holds: the picker keeps reading pages until that many
        rows are visible, so a page whose items are mostly hidden (already in the Bill of Materials) does not leave the list short.
        """
        data = self._client.get_json(search_path(workspace_id, text, groups, offset, PAGE_SIZE, revision))
        return {**parse_search(data, workspace_id, parent_id), "limit": PAGE_SIZE}

    def members(self, workspace_id: str, item_id: str) -> Dict[str, List[str]]:
        """``{"ids", "numbers"}`` of the items the Bill of Materials of ``item_id`` holds now (the item itself included).

        It is the working Bill of Materials of ``item_id``, the one a publish changes. A line may point at another revision of an item than a
        search finds, so the picker matches on the number too."""
        path = (f"{WORKSPACES}/{workspace_id}/items/{item_id}/bom"
                f"?depth={MEMBERS_DEPTH}&effectiveDate={date.today().isoformat()}&revisionBias={WORKING_BIAS}&rootId={item_id}")
        return parse_members(self._client.get_json(path, accept=ACCEPT))

"""Find the Components workspace item that stands for a part, to fill an item's component linking field.

The field is a picklist whose options are the items of the Components workspace (``CUSTOM_LOOKUP_WS_COMPONENTS_...``),
so the lookup is asked for the options whose text matches the item number. The option's ``link`` is what the field takes.
"""

import re
from typing import Any, Iterable, List, NamedTuple, Tuple
from urllib.parse import quote

from ..core.logging_setup import get_logger
from ..core.shapes import dict_rows, dig
from .client import LOOKUPS, WORKSPACES, FmClient, last_segment
from .pages import ITEM_LINK
from .search_query import WORKING
from .ttl_cache import TtlCache

log = get_logger("fm.components")

SEARCH_RESULTS = "/api/v3/search-results"
COMPONENTS_WORKSPACE = "Components"   # what Fusion Manage calls the workspace of the components
WORKSPACES_LIMIT = 200   # workspaces asked for when looking for it
CANDIDATES = 25   # options asked for when searching by number
SEARCH_LIMIT = 50   # results asked for when searching for the working version
SHOWN = 5   # matches named in the message when more than one fits
NO_NUMBER = "The item has no number to look up."
_URN = re.compile(r"\.(\d+)\.(\d+)\s*$")   # urn:adsk.plm:tenant.workspace.item:TENANT.<workspace>.<item>
_WORKING = re.compile(r"\[REV:\s*w(?:orking)?\s*\]", re.IGNORECASE)   # "[REV:w]": how Fusion Manage names the working version
_WORKSPACES = TtlCache(600)   # the Components workspace's id by tenant: it does not change, and the Export window asks twice


class Candidate(NamedTuple):
    """A record that may be the one an item number stands for."""

    link: str   # its API link
    title: str   # ``PN-1 - Axle``
    version: str   # ``[REV:w]`` (empty when the answer gives none)


def _matches(title: str, number: str) -> bool:
    """The option is the number alone, or starts with it and then a separator (``PN-1 - Axle``), not a longer number (``PN-10``)."""
    title, number = title.strip().casefold(), number.strip().casefold()
    return title == number or bool(re.match(re.escape(number) + r"(?![0-9a-z])", title))


def is_working(version: str) -> bool:
    """Whether a search result's ``version`` (``[REV:w]``) says it is the working version of its record."""
    return bool(_WORKING.search(version))


def manage_link(urn: str, url: str) -> str:
    """The API link ``/api/v3/workspaces/<workspace>/items/<item>`` of the item a Data Model component is linked to ("" if neither says)."""
    match = _URN.search(urn) or ITEM_LINK.search(url)
    if not match:
        return ""
    first, second = match.groups()
    return f"{WORKSPACES}/{first}/items/{second}"


def link_ids(link: str) -> Tuple[str, str]:
    """``(workspace id, item id)`` of an item's API link (``/api/v3/workspaces/<workspace>/items/<item>``), or ``("", "")``."""
    match = ITEM_LINK.search(link)
    return match.groups() if match else ("", "")


def _named(candidates: Iterable[Candidate]) -> str:
    """The first few of ``candidates``, each by title, version and id, for a message that says which ones fit."""
    return ", ".join(f"{c.title} {c.version} ({last_segment(c.link)})" for c in list(candidates)[:SHOWN])


def parse_workspace_id(data: Any, title: str = COMPONENTS_WORKSPACE) -> str:
    """The id of the workspace called ``title`` (ignoring case and space) in the answer listing the workspaces ("" when there is none)."""
    for row in dict_rows(dig(data, "items")):
        name = str(row.get("title") or row.get("name") or "")
        if name.strip().casefold() == title.casefold():
            return last_segment(row.get("link") or row.get("__self__"))
    return ""


def _the_one(hits: List[Candidate], none: str, many: str) -> Tuple[str, str]:
    """``(link, "")`` when ``hits`` is one record, else ``("", reason)``: ``none`` when there is no record, ``many`` when there are several."""
    if len(hits) == 1:
        return hits[0].link, ""
    return "", many if hits else none


class ComponentService:
    """Finds components in the Components workspace and in the picklist of the component linking field."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def workspace_id(self) -> str:
        """The id of the Components workspace: the workspace of Fusion Manage called ``Components`` ("" when there is none). Kept for a while,
        since it is asked for when the Export window opens and again when it exports."""
        key = self._client.base_url
        found = _WORKSPACES.get(key)
        if found is None:
            found = parse_workspace_id(self._client.get_json(f"{WORKSPACES}?offset=0&limit={WORKSPACES_LIMIT}"))
            if found:
                _WORKSPACES.put(key, found)
        return found

    def find_working(self, number: str) -> Tuple[str, str]:
        """``(link, "")`` of the working version of the record for this item number in the Components workspace, else ``("", reason)``.

        The search lists a record's working version: ``GET /api/v3/search-results?query=<number> AND (workspaceId=<workspace>)&revision=3``
        (``revision`` 1 is the latest revision, 2 every revision, 3 the working version). Each result has its ``descriptor``
        (``PN-1 - Axle``), its ``version`` (``[REV:w]``) and its link (``__self__``). The picklist of the component linking field is for
        publish only: it names no workspace and has an option for every revision.
        """
        if not number:
            return "", NO_NUMBER
        workspace_id = self.workspace_id()
        if not workspace_id:
            return "", f"No workspace called {COMPONENTS_WORKSPACE} could be found in Fusion Manage."
        query = quote(f"{number} AND (workspaceId={workspace_id})")
        data = self._client.get_json(f"{SEARCH_RESULTS}?isFullQuery=true&limit={SEARCH_LIMIT}&offset=0&page=1&query={query}&revision={WORKING}")
        found = [Candidate(str(r.get("__self__") or ""), str(r.get("descriptor") or ""), str(r.get("version") or ""))
                 for r in dict_rows(dig(data, "items"))]
        log.info("Working versions for %s in workspace %s: %s", number, workspace_id, [f"{c.title} {c.version} {c.link}" for c in found])
        hits = [c for c in found if c.link and _matches(c.title, number)]
        working = [c for c in hits if is_working(c.version)] or hits   # the filter gives working versions; the version is checked anyway
        return _the_one(working, f"No working version of the component {number} in the Components workspace ({len(found)} result(s) came back for it).",
                        f"{len(working)} working versions match {number}: {_named(working)}")

    def find(self, lookup: str, number: str) -> Tuple[str, str]:
        """``(link, "")`` of the one option for this item number, else ``("", reason)``."""
        if not number:
            return "", NO_NUMBER
        data = self._client.get_json(f"{LOOKUPS}/{lookup}?offset=0&limit={CANDIDATES}&filter={quote(number)}&asc=&desc=")
        options: List[Candidate] = [Candidate(str(r["link"]), str(r.get("title") or ""), str(r.get("version") or ""))
                                    for r in dict_rows(dig(data, "items")) if r.get("link")]
        hits = [o for o in options if _matches(o.title, number)]
        log.debug("Component options for %s: %s", number, [o.title for o in options])
        return _the_one(hits, f"No component matching {number} in {lookup} ({len(options)} option(s) came back for it).",
                        f"{len(hits)} components match {number}: {_named(hits)} - the Data Model has to say which")

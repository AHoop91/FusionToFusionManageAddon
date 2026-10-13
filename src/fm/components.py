"""Find the Components workspace item that stands for a part, to fill an item's component linking field.

The field is a picklist whose options are the items of the Components workspace (``CUSTOM_LOOKUP_WS_COMPONENTS_...``),
so the lookup is asked for the options whose text matches the item number. The option's ``link`` is what the field takes.
"""

import re
from typing import Dict, List, Tuple
from urllib.parse import quote

from ..core.logging_setup import get_logger
from .client import LOOKUPS, WORKSPACES, FmClient, last_segment
from .ttl_cache import TtlCache

log = get_logger("fm.components")

_URN = re.compile(r"\.(\d+)\.(\d+)\s*$")   # urn:adsk.plm:tenant.workspace.item:TENANT.<workspace>.<item>
_URL = re.compile(r"workspaces/(\d+)/items/(\d+)")
CANDIDATES = 25   # options asked for when searching by number
SEARCH_LIMIT = 50   # results asked for when searching for the working version
COMPONENTS_WORKSPACE = "Components"   # what Fusion Manage calls the workspace of the components
WORKSPACES_LIMIT = 200
_WORKSPACES = TtlCache(600)   # the Components workspace's id by tenant: it does not change, and the Export window asks twice


def _matches(title: str, number: str) -> bool:
    """The option is the number alone, or starts with it and then a separator (``PN-1 - Axle``), not a longer number (``PN-10``)."""
    title, number = title.strip().casefold(), number.strip().casefold()
    return title == number or bool(re.match(re.escape(number) + r"(?![0-9a-z])", title))


_WORKING = re.compile(r"\[REV:\s*w(?:orking)?\s*\]", re.IGNORECASE)   # "[REV:w]": how Fusion Manage names the working version


def is_working(version: str) -> bool:
    """Whether a search result's ``version`` (``[REV:w]``) says it is the working version of its record."""
    return bool(_WORKING.search(version))


SEARCH = "/api/v3/search-results"
WORKING_REVISION = "3"   # the search's ``revision`` filter: 1 gives the latest revision of each record, 2 every revision, 3 the working version


def manage_link(urn: str, url: str) -> str:
    """The API link ``/api/v3/workspaces/<workspace>/items/<item>`` of the item a Data Model component is linked to ("" if neither says)."""
    match = _URN.search(urn) or _URL.search(url)
    if not match:
        return ""
    first, second = match.groups()
    return f"{WORKSPACES}/{first}/items/{second}"


def link_ids(link: str) -> Tuple[str, str]:
    """``(workspace id, item id)`` of an item's API link (``/api/v3/workspaces/<workspace>/items/<item>``), or ``("", "")``."""
    match = _URL.search(link)
    return match.groups() if match else ("", "")


class ComponentService:
    """Finds components in the picklist of the component linking field."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def workspace_id(self) -> str:
        """The id of the Components workspace: the workspace of Fusion Manage called ``Components`` ("" when there is none). Kept for a while,
        since it is asked for when the Export window opens and again when it exports."""
        key = self._client.base_url
        found = _WORKSPACES.get(key)
        if found is None:
            data = self._client.get_json(f"{WORKSPACES}?offset=0&limit={WORKSPACES_LIMIT}")
            rows = data.get("items") if isinstance(data, dict) else None
            titled = [(str(r.get("title") or r.get("name") or ""), str(r.get("link") or r.get("__self__") or ""))
                      for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
            log.info("Workspaces: %s", [f"{title} ({link})" for title, link in titled])
            found = next((last_segment(link) for title, link in titled if title.strip().casefold() == COMPONENTS_WORKSPACE.casefold()), "")
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
            return "", "The item has no number to look up."
        workspace_id = self.workspace_id()
        if not workspace_id:
            return "", f"No workspace called {COMPONENTS_WORKSPACE} could be found in Fusion Manage."
        query = quote(f"{number} AND (workspaceId={workspace_id})")
        data = self._client.get_json(f"{SEARCH}?isFullQuery=true&limit={SEARCH_LIMIT}&offset=0&page=1&query={query}&revision={WORKING_REVISION}")
        rows = data.get("items") if isinstance(data, dict) else None
        found = [(str(r.get("__self__") or ""), str(r.get("descriptor") or ""), str(r.get("version") or ""))
                 for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        hits = [(link, descriptor, version) for link, descriptor, version in found if link and _matches(descriptor, number)]
        log.info("Working versions for %s in workspace %s: %s", number, workspace_id, [f"{d} {v} {link}" for link, d, v in found])
        working = [h for h in hits if is_working(h[2])] or hits   # the filter gives working versions; the version is checked anyway
        if len(working) == 1:
            return working[0][0], ""
        if not working:
            return "", f"No working version of the component {number} in the Components workspace ({len(found)} result(s) came back for it)."
        return "", f"{len(working)} working versions match {number}: " + ", ".join(f"{d} {v} ({last_segment(link)})" for link, d, v in working[:5])

    def find(self, lookup: str, number: str) -> Tuple[str, str]:
        """``(link, "")`` of the one option for this item number, else ``("", reason)``."""
        if not number:
            return "", "The item has no number to look up."
        data = self._client.get_json(f"{LOOKUPS}/{lookup}?offset=0&limit={CANDIDATES}&filter={quote(number)}&asc=&desc=")
        rows = data.get("items") if isinstance(data, dict) else None
        options: List[Dict[str, str]] = [{"link": str(r["link"]), "title": str(r.get("title") or ""), "version": str(r.get("version") or "")}
                                         for r in rows if isinstance(r, dict) and r.get("link")] if isinstance(rows, list) else []
        hits = [o for o in options if _matches(o["title"], number)]
        log.debug("Component options for %s: %s", number, [o["title"] for o in options])
        if len(hits) == 1:
            return hits[0]["link"], ""
        if not hits:
            return "", f"No component matching {number} in {lookup} ({len(options)} option(s) came back for it)."
        return "", f"{len(hits)} components match {number}: " + ", ".join(f"{o['title']} {o['version']} ({last_segment(o['link'])})" for o in hits[:5]) + " - the Data Model has to say which"

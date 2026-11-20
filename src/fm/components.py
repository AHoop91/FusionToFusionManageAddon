"""The Components workspace: its id, the fields of one of its records (the design's lineage and asset ids, the revision and state), and the
options of the component linking picklist for an item number.

That field is a picklist whose options are the items of the Components workspace (``CUSTOM_LOOKUP_WS_COMPONENTS_...``), so the lookup is asked
for the options whose text matches the item number. The option's ``link`` is what the field takes.
"""

import re
from typing import Any, List, NamedTuple, Tuple
from urllib.parse import quote

from ..core.logging_setup import get_logger
from ..core.i18n import t
from ..core.shapes import dict_rows, dig
from .client import LOOKUPS, WORKSPACES, FmApiError, FmClient, last_segment
from .item_view import revision_and_state
from .items import collect_values
from .pages import ITEM_LINK
from .ttl_cache import TtlCache

log = get_logger("fm.components")

COMPONENTS_WORKSPACE = "Components"   # what Fusion Manage calls the workspace of the components
WORKSPACES_LIMIT = 200   # workspaces asked for when looking for it
CANDIDATES = 25   # options asked for when searching by number
LINEAGE = re.compile(r"urn:adsk\.wipprod:dm\.lineage:[A-Za-z0-9_-]+")   # the id Fusion finds a design's data file by
LINEAGE_FIELD = "LINEAGE_URN"   # the Components workspace field that holds it
ASSET_FIELD = "ASSET_URN"   # and the one that holds the design's asset id (it is not part of the Data Model's model id)
_URN = re.compile(r"\.(\d+)\.(\d+)\s*$")   # urn:adsk.plm:tenant.workspace.item:TENANT.<workspace>.<item>
_WORKING = re.compile(r"\[REV:\s*w(?:orking)?\s*\]", re.IGNORECASE)   # "[REV:w]": how Fusion Manage names the working version
_WORKSPACES = TtlCache(600)   # the Components workspace's id by tenant: it does not change, and the Export window asks twice


class Candidate(NamedTuple):
    """A record that may be the one an item number stands for."""

    link: str   # its API link
    title: str   # ``PN-1 - Axle``
    version: str   # ``[REV:w]`` (empty when the answer gives none)


def number_matches(title: str, number: str) -> bool:
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


def parse_workspace_id(data: Any, title: str = COMPONENTS_WORKSPACE) -> str:
    """The id of the workspace called ``title`` (ignoring case and space) in the answer listing the workspaces ("" when there is none)."""
    for row in dict_rows(dig(data, "items")):
        name = str(row.get("title") or row.get("name") or "")
        if name.strip().casefold() == title.casefold():
            return last_segment(row.get("link") or row.get("__self__"))
    return ""


class ComponentService:
    """Reads the Components workspace and the picklist of the component linking field through an ``FmClient``."""

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

    def _field(self, link: str, field_id: str) -> str:
        """The text of a field of the item at ``link``: "" when the item holds no value for it, or ``link`` is not an item's (nothing is read)."""
        workspace_id, item_id = link_ids(link)
        if not item_id:
            return ""
        return str(collect_values(self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}")).get(field_id) or "")

    def design_file(self, link: str) -> str:
        """The lineage id (``urn:adsk.wipprod:dm.lineage:...``) of the Fusion design the component item at ``link`` was published from: what Fusion
        opens the design by. It is the item's Lineage URN field. Raises ``FmApiError`` when ``link`` is not an item's, or the item has no design."""
        found = self._field(link, LINEAGE_FIELD)
        if not LINEAGE.fullmatch(found):
            raise FmApiError(t("data.fm_no_design_file"))
        return found

    def asset(self, link: str) -> str:
        """The asset id of the Fusion design the component item at ``link`` was published from (its Asset URN field): what the Items workspace's
        ``COMPONENT_ASSET_URN`` copies. Raises ``FmApiError`` when ``link`` is not an item's, or the item has no asset id."""
        found = self._field(link, ASSET_FIELD)
        if not found:
            raise FmApiError(t("data.fm_no_asset"))
        return found

    def revision_and_state(self, link: str) -> Tuple[str, str]:
        """``(revision, life cycle state)`` of the component record at ``link`` (the Data Model gives it, see ``read_manage_item``)."""
        return revision_and_state(self._client.get_json(link))

    def matching(self, lookup: str, number: str) -> List[Candidate]:
        """Every option of the picklist for this item number (one for each revision of the component). Raises ``FmApiError`` with the reason
        when the item has no number or no option matches it."""
        if not number:
            raise FmApiError(t("data.fm_no_number"))
        data = self._client.get_json(f"{LOOKUPS}/{lookup}?offset=0&limit={CANDIDATES}&filter={quote(number)}&asc=&desc=")
        options: List[Candidate] = [Candidate(str(r["link"]), str(r.get("title") or ""), str(r.get("version") or ""))
                                    for r in dict_rows(dig(data, "items")) if r.get("link")]
        hits = [o for o in options if number_matches(o.title, number)]
        log.debug("Component options for %s: %s", number, [o.title for o in options])
        if not hits:
            raise FmApiError(t("data.fm_no_component", number=number, lookup=lookup, count=len(options)))
        return hits

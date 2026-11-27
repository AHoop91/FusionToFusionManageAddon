"""Find the manufacturing bills of materials (MBOM) of a design: the items of the Items workspace that were made from it.

A design can have several MBOM items, and their item numbers differ, so the number cannot find them. Each carries the design's lineage id
in the derived field ``COMPONENT_LINEAGE_URN`` and its asset id in ``COMPONENT_ASSET_URN`` (see "Multi-manufacturing bill of materials"
in the configuration help), so a search on both returns every one. It returns each version of an item, so the search is limited to the working
version. It is a v1 search: the v3 search takes no ``:`` in a term, and a lineage id has two.

The lineage id is the design's (the Data Model gives it). The asset id is not in the Data Model: it is read from the design's record in the
Components workspace, which Fusion Manage keeps for the design (see ``ComponentService.asset``).
"""

from typing import Dict, List

from ..core.i18n import t
from ..core.logging_setup import get_logger
from .client import FmApiError, FmClient
from .components import LINEAGE, ComponentService
from .v1_search import DESCRIPTOR_TAB, IS, IS_TRUE, LIFECYCLE, Field, Filter, Sort, V1SearchService
from .v3_search import LATEST, ItemFinder, number_key

log = get_logger("fm.mbom")

# The fields of the Items workspace that hold the lineage id and the asset id of the item's component.
ITEM_LINEAGE_FIELD = "COMPONENT_LINEAGE_URN"
ITEM_ASSET_FIELD = "COMPONENT_ASSET_URN"
DESCRIPTOR_FIELD = "DESCRIPTOR"   # the item's title: what the list of MBOM items shows
WORKING_FIELD = "WORKING"   # on the Lifecycle tab: the working version of an item


class MbomService:
    """Finds the MBOM items of a design through an ``FmClient``. Call from a worker thread; a failed search raises."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def number_taken(self, workspace_id: str, number: str) -> bool:
        """Whether an item of the workspace already has this item number (whatever its version), so a new MBOM cannot take it. A failed search
        raises: it is not "free"."""
        wanted = number.strip().lower()
        return any(number_key(hit["descriptor"]) == wanted for hit in ItemFinder(self._client, LATEST).search(workspace_id, number))

    def of_component(self, workspace_id: str, record_link: str, number_field: str) -> List[Dict[str, str]]:
        """The items of the workspace made from the component whose record in the Components workspace is at ``record_link``: ``find`` with the
        lineage id read from that record (its Lineage URN), as the component may be a design of its own, not the open one. Raises ``FmApiError``
        when the record has no design or no asset id, or the search fails."""
        lineage, asset = ComponentService(self._client).identity(record_link)   # one read of the record
        return self._search(workspace_id, lineage, asset, number_field)

    def find(self, workspace_id: str, lineage: str, record_link: str, number_field: str) -> List[Dict[str, str]]:
        """The items of the workspace made from the design with this lineage id and the asset id of its Components record (both must match),
        as ``{"id", "number", "descriptor"}`` in the order the search gives them. Only the working version of each item is searched for.

        ``record_link`` is the API link of the design's record in the Components workspace, where the asset id is read. ``number_field`` is the
        id of the field that holds the item number (the field the ``item_number`` source is mapped to). Raises ``FmApiError`` with the reason
        when ``lineage`` is not a lineage id, the record has no asset id or the search fails: a failed search is not "no MBOM"."""
        if not LINEAGE.fullmatch(lineage):
            raise FmApiError(t("data.fm_bad_lineage"))
        return self._search(workspace_id, lineage, ComponentService(self._client).asset(record_link), number_field)

    def _search(self, workspace_id: str, lineage: str, asset: str, number_field: str) -> List[Dict[str, str]]:
        """The search ``find`` and ``of_component`` make, for a lineage id and an asset id already known."""
        log.info("Looking for the MBOM items of workspace %s with %s=%s and %s=%s", workspace_id, ITEM_LINEAGE_FIELD, lineage, ITEM_ASSET_FIELD, asset)
        fields = [Field(ITEM_LINEAGE_FIELD), Field(ITEM_ASSET_FIELD), Field(number_field), Field(DESCRIPTOR_FIELD, DESCRIPTOR_TAB)]
        filters = [Filter(ITEM_LINEAGE_FIELD, IS, lineage), Filter(ITEM_ASSET_FIELD, IS, asset), Filter(WORKING_FIELD, IS_TRUE, "", LIFECYCLE)]
        rows = V1SearchService(self._client).rows(workspace_id, fields, [Sort(ITEM_LINEAGE_FIELD)], filters)
        return [{"id": row.dms_id, "number": row.values.get(number_field, ""), "descriptor": row.values.get(DESCRIPTOR_FIELD, "")} for row in rows]

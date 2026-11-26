"""Search a workspace through the v1 search API, which the v3 search cannot do for the Grid tab.

``POST /api/rest/v1/workspaces/{id}/items/search`` takes a search definition: the fields to return, a sort and filters, each naming the tab
a field lives on (``fieldTypeID``). Reading a Grid tab's rows is the reason this exists (``GRIDVIEW`` fields).

What a live call showed is in ``dev/finding-items.md``: the answer is not wrapped and uses the casing ``rowId``/``dmsId``, a search needs a
sort, and a search that matches nothing is answered 204 with no body. How a Grid column that has rows is answered, and which key a text field
keeps its text under (``formattedValue`` is not seen), are still **Assumed**. An answer without ``totalResultCount`` raises.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from ..core.i18n import t
from ..core.shapes import as_dict, dict_rows, dig, whole
from .client import NO_CONTENT, FmApiError, FmClient

SEARCH_PATH = "/api/rest/v1/workspaces/{workspace}/items/search"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 999    # the service wants a size below 1000
MAX_PAGES = 100        # most pages ``rows`` reads, so a search that never ends cannot run for ever

# ``fieldTypeID``: the tab a field lives on.
ITEM_DETAILS = 0
GRIDVIEW = 2
LIFECYCLE = 10
DESCRIPTOR_TAB = 15   # the tab of the item's descriptor (its field id is ``DESCRIPTOR``, as in the v1 help's example)

# ``filterType.filterID``. For fields whose data type is Alpha Numeric (4): text, email, URL, a picklist that keeps its label.
CONTAINS = 2
IS = 15
# For a true/false field: it matches when the field is true, and takes no value (the help's own example of LATEST_RELEASE).
IS_TRUE = 13

AND = "AND"
OR = "OR"


@dataclass(frozen=True)
class Field:
    """A field to return, by its id and the tab it lives on."""
    id: str
    type_id: int = ITEM_DETAILS


@dataclass(frozen=True)
class Filter:
    """A condition on one field: ``filter_id`` is one of the constants above (or one the service lists for the field's data type)."""
    field_id: str
    filter_id: int
    value: str = ""
    type_id: int = ITEM_DETAILS


@dataclass(frozen=True)
class Sort:
    """How the rows are ordered: by one field, ascending unless ``descending``."""
    field_id: str
    type_id: int = ITEM_DETAILS
    descending: bool = False


@dataclass(frozen=True)
class V1Row:
    """A matching item: its id, ``field id -> display text`` and every ``(field id, display text)`` entry in the order sent. A field the item
    leaves blank has no entry. ``values`` keeps the last entry of a field, so a Grid column that comes once for each row of the grid is in
    ``entries`` only (how v1 answers a search that returns a Grid column has not been seen)."""
    dms_id: str
    values: Dict[str, str]
    entries: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class V1Page:
    """One page of an answer: how many items match in all, and the rows of this page."""
    total: int
    rows: List[V1Row]


@dataclass(frozen=True)
class Paging:
    """Which page to ask for (from 1) and how many rows it holds."""
    page: int = 1
    size: int = DEFAULT_PAGE_SIZE


def build_definition(fields: Sequence[Field], sort: Sequence[Sort], filters: Sequence[Filter] = (), paging: Paging = Paging()) -> Dict[str, Any]:
    """The search definition to send: every filter must match (``AND``), but a single filter is sent with ``OR``, as the service requires. A ``sort`` is required: the service refuses a
    search with none ("sortFieldsList is not specified", seen live)."""
    if paging.page < 1 or not 0 < paging.size <= MAX_PAGE_SIZE:
        raise ValueError(f"page {paging.page} and page size {paging.size} are not allowed")
    if not sort:
        raise ValueError("a v1 search needs a sort")
    return {
        "pageNo": paging.page,
        "pageSize": paging.size,
        "logicClause": OR if len(filters) == 1 else AND,
        "fields": [{"fieldID": f.id, "fieldTypeID": f.type_id} for f in fields],
        "sort": [{"fieldID": s.field_id, "fieldTypeID": s.type_id, "sortDescending": s.descending} for s in sort],
        "filter": [{"fieldID": f.field_id, "fieldTypeID": f.type_id, "filterType": {"filterID": f.filter_id}, "filterValue": f.value}
                   for f in filters],
    }


def _text(field_data: Any) -> str:
    """The text of one ``fieldData``: ``formattedValue``, or ``label`` for a picklist (the v1 page shows both)."""
    data = as_dict(field_data)
    for key in ("formattedValue", "label", "value"):
        if data.get(key) is not None:
            return str(data[key])
    return ""


def parse_page(data: Any) -> V1Page:
    """The rows of a search answer. Raises when the answer has no ``totalResultCount``, since it is then not a search answer."""
    if not isinstance(data, dict) or "totalResultCount" not in data:
        raise FmApiError(t("data.fm_v1_search_unexpected"))
    rows = []
    for row in dict_rows(data.get("row")):
        entries = dict_rows(dig(row, "fields", "entry"))
        pairs = tuple((str(e.get("key")), _text(e.get("fieldData"))) for e in entries if e.get("key"))
        rows.append(V1Row(str(row.get("dmsId") or ""), dict(pairs), pairs))
    return V1Page(whole(data.get("totalResultCount")), rows)


class V1SearchService:
    """Searches one workspace through the v1 API. Call from a worker thread. ``page_size`` is how many rows ``rows`` asks for in each page."""

    def __init__(self, client: FmClient, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        self._client = client
        self._page_size = page_size

    def page(self, workspace_id: str, definition: Dict[str, Any]) -> V1Page:
        """One page of the items that match ``definition`` (see ``build_definition``)."""
        workspace = str(workspace_id).strip()
        if not workspace.isdigit():
            raise FmApiError(t("data.fm_bad_address"))
        result = self._client.send_json("POST", SEARCH_PATH.format(workspace=workspace), definition)
        if result.status == NO_CONTENT:   # seen live: a search that matches nothing is answered with no body at all
            return V1Page(0, [])
        return parse_page(result.data)

    def rows(self, workspace_id: str, fields: Sequence[Field], sort: Sequence[Sort], filters: Sequence[Filter] = ()) -> List[V1Row]:
        """Every matching row, reading page after page until the total is reached.

        Raises when the search would need more than ``MAX_PAGES`` pages, and does not return a cut-off list."""
        found: List[V1Row] = []
        for number in range(1, MAX_PAGES + 1):
            page = self.page(workspace_id, build_definition(fields, sort, filters, Paging(number, self._page_size)))
            found.extend(page.rows)
            if not page.rows or len(found) >= page.total:
                return found
        raise FmApiError(t("data.fm_v1_search_too_long", pages=MAX_PAGES))

"""Search a workspace through the v1 search API, which the v3 search cannot do for the Grid tab.

``POST /api/rest/v1/workspaces/{id}/items/search`` takes a search definition: the fields to return, a sort and filters, each naming the tab
a field lives on (``fieldTypeID``). Reading a Grid tab's rows is the reason this exists (``GRIDVIEW`` fields).

Every key of the request and answer is **Assumed** from the v1 help page; none has been seen in the add-in log. The page contradicts itself on
casing (``rowID``/``rowId``) and on a ``reportResult`` wrapper, so this reads the casing of its example and raises when the answer has no
``totalResultCount``, so the first live answer settles it.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from ..core.i18n import t
from ..core.shapes import as_dict, dict_rows, dig, whole
from .client import FmApiError, FmClient

SEARCH_PATH = "/api/rest/v1/workspaces/{workspace}/items/search"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 999    # the service wants a size below 1000
MAX_PAGES = 100        # most pages ``rows`` reads, so a search that never ends cannot run for ever

# ``fieldTypeID``: the tab a field lives on.
ITEM_DETAILS = 0
GRIDVIEW = 2
LOG_INFO = 3
LIFECYCLE = 10
ALL_FIELDS = 99        # search across tabs

# ``filterType.filterID`` for fields whose data type is Alpha Numeric (4): text, email, URL, a picklist that keeps its label.
CONTAINS = 2
STARTS_WITH = 3
ENDS_WITH = 4
DOES_NOT_CONTAIN = 5
IS = 15
IS_BLANK = 20
NOT_BLANK = 21

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
    field_id: str
    type_id: int = ITEM_DETAILS
    descending: bool = False


@dataclass(frozen=True)
class V1Row:
    """A matching item: its id and ``field id -> display text``. A field the item leaves blank has no entry."""
    dms_id: str
    values: Dict[str, str]


@dataclass(frozen=True)
class V1Page:
    total: int
    rows: List[V1Row]


def build_definition(fields: Sequence[Field], filters: Sequence[Filter] = (), sort: Sequence[Sort] = (), logic: str = AND,
                     page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> Dict[str, Any]:
    """The search definition to send. A single filter is sent with ``OR``, as the service requires."""
    if page < 1 or not 0 < page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page {page} and page size {page_size} are not allowed")
    return {
        "pageNo": page,
        "pageSize": page_size,
        "logicClause": OR if len(filters) == 1 else logic,
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
        rows.append(V1Row(str(row.get("dmsId") or ""), {str(e.get("key")): _text(e.get("fieldData")) for e in entries if e.get("key")}))
    return V1Page(whole(data.get("totalResultCount")), rows)


class V1SearchService:
    """Searches one workspace through the v1 API. Call from a worker thread."""

    def __init__(self, client: FmClient) -> None:
        self.client = client

    def page(self, workspace_id: str, definition: Dict[str, Any]) -> V1Page:
        """One page of the items that match ``definition`` (see ``build_definition``)."""
        workspace = str(workspace_id).strip()
        if not workspace.isdigit():
            raise FmApiError(t("data.fm_bad_address"))
        result = self.client.send_json("POST", SEARCH_PATH.format(workspace=workspace), definition)
        return parse_page(result.data)

    def rows(self, workspace_id: str, fields: Sequence[Field], filters: Sequence[Filter] = (), sort: Sequence[Sort] = (),
             logic: str = AND, page_size: int = DEFAULT_PAGE_SIZE, limit: Optional[int] = None) -> List[V1Row]:
        """Every matching row (at most ``limit``), reading page after page until the total is reached.

        Raises when the search would need more than ``MAX_PAGES`` pages, and does not return a cut-off list."""
        found: List[V1Row] = []
        for number in range(1, MAX_PAGES + 1):
            page = self.page(workspace_id, build_definition(fields, filters, sort, logic, number, page_size))
            found.extend(page.rows)
            if not page.rows or len(found) >= page.total or (limit is not None and len(found) >= limit):
                return found if limit is None else found[:limit]
        raise FmApiError(t("data.fm_v1_search_too_long", pages=MAX_PAGES))

"""The fields Fusion Manage works out from the item a linking picklist field links to (its derived fields).

A field that links to another workspace's item can have derived fields in its own workspace: Fusion Manage copies them from the linked item,
and refuses an item whose derived values it did not get ("Derived value ... does not match the source field value"). The pivot of the
linking field, asked for the linked item, gives them: ``GET /api/v3/workspaces/<ws>/views/1/pivots/<field>?pivotItemId=<item id>``.
"""

from typing import Any, List, NamedTuple

from ..core.i18n import t
from ..core.shapes import rows_in
from .client import VIEW, WORKSPACES, FmApiError, FmClient, last_segment


class Derived(NamedTuple):
    """One derived field of the linked item: its id, its value and the link of the section it is written in."""

    field_id: str
    value: Any
    section: str


def parse_pivot(data: Any) -> List[Derived]:
    """The derived fields the answer of a pivot lists, each with its value and section. Raises ``FmApiError`` when a field names no id or its
    section has no link: the item could not be written with it."""
    derived: List[Derived] = []
    for section in rows_in(data, "sections"):
        section_link = str(section.get("link") or "")
        for field in rows_in(section, "fields"):
            field_id = last_segment(field.get("__self__"))
            if not field_id or not section_link:
                raise FmApiError(t("data.fm_pivot_unreadable"))
            derived.append(Derived(field_id, field.get("value"), section_link))
    return derived


class PivotService:
    """Reads the derived fields of a linking field through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def derived(self, workspace_id: str, field_id: str, item_id: str) -> List[Derived]:
        """The derived fields that linking field ``field_id`` of workspace ``workspace_id`` takes from the item ``item_id`` it links to."""
        return parse_pivot(self._client.get_json(f"{WORKSPACES}/{workspace_id}/{VIEW}/pivots/{field_id}?pivotItemId={item_id}"))

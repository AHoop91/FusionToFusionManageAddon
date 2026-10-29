"""The change log of an item: what was done to it, when and by whom, newest first.

``GET /api/v3/workspaces/{ws}/items/{id}/logs?desc=timeStamp&limit=100&offset=0`` answers with ``totalCount`` and a page of ``items``
(each with a ``timeStamp``, ``user``, ``action``, a ``description`` and the ``details`` of the fields it changed). Only one page is read at
a time, so a long log opens as fast as a short one; the page asks for the next when the user does.
"""

from typing import Any, Dict

from ..core.shapes import dict_rows, dig, whole
from .client import WORKSPACES, FmApiError, FmClient

PAGE_SIZE = 100   # the most the API gives in one answer


def _text(value: Any) -> str:
    """``value`` as text, "" for none. A value of 0 or False is kept: it may be what a field was changed from or to."""
    return "" if value is None else str(value)


def _row(entry: Dict[str, Any]) -> Dict[str, Any]:
    changes = [{"field": _text(d.get("fieldName")), "old": _text(d.get("oldValue")), "new": _text(d.get("newValue"))}
               for d in dict_rows(entry.get("details"))]
    return {"date": _text(entry.get("timeStamp")), "user": _text(dig(entry, "user", "title")), "action": _text(dig(entry, "action", "shortName")),
            "description": _text(entry.get("description")), "changes": changes}


def parse_change_log(data: Any, offset: int) -> Dict[str, Any]:
    """``{"rows": [...], "total": n, "next": offset of the next page or None}`` from a page of the log."""
    if data is None:   # 204: nothing logged
        return {"rows": [], "total": 0, "next": None}
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise FmApiError("Fusion Manage did not return the change log of this item.")
    total = whole(data.get("totalCount"))
    following = offset + len(data["items"])   # every entry counts toward the offset, including one that is left out of the rows
    return {"rows": [_row(entry) for entry in dict_rows(data["items"])], "total": total,
            "next": following if data["items"] and following < total else None}


class ChangeLogService:
    """Reads a page of the change log of an item through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str, offset: int = 0) -> Dict[str, Any]:
        offset = max(0, whole(offset))
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}/logs?desc=timeStamp&limit={PAGE_SIZE}&offset={offset}")
        return parse_change_log(data, offset)

"""The change log of an item: what was done to it, when and by whom, newest first.

``GET /api/v3/workspaces/{ws}/items/{id}/logs?desc=timeStamp&limit=100&offset=0`` answers with ``totalCount`` and a page of ``items``
(each with a ``timeStamp``, ``user``, ``action``, a ``description`` and the ``details`` of the fields it changed). Only one page is read at
a time, so a long log opens as fast as a short one; the page asks for the next when the user does.
"""

from typing import Any, Dict

from ..core.shapes import as_dict, dict_rows
from .client import WORKSPACES, FmApiError, FmClient

PAGE_SIZE = 100   # the most the API gives in one answer


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def parse_change_log(data: Any, offset: int) -> Dict[str, Any]:
    """``{"rows": [...], "total": n, "next": offset of the next page or None}`` from a page of the log."""
    if data is None:   # 204: nothing logged
        return {"rows": [], "total": 0, "next": None}
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise FmApiError("Fusion Manage did not return the change log of this item.")
    rows = []
    for entry in dict_rows(data["items"]):
        user = as_dict(entry.get("user"))
        action = as_dict(entry.get("action"))
        changes = [{"field": _text(d.get("fieldName")), "old": _text(d.get("oldValue")), "new": _text(d.get("newValue"))}
                   for d in dict_rows(entry.get("details"))]
        rows.append({"date": _text(entry.get("timeStamp")), "user": _text(user.get("title")), "action": _text(action.get("shortName")),
                     "description": _text(entry.get("description")), "changes": changes})
    total = int(data.get("totalCount") or 0)
    following = offset + len(data["items"])
    return {"rows": rows, "total": total, "next": following if data["items"] and following < total else None}


class ChangeLogService:
    """Reads a page of the change log of an item through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str, offset: int = 0) -> Dict[str, Any]:
        offset = max(0, int(offset))
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}/logs?desc=timeStamp&limit={PAGE_SIZE}&offset={offset}")
        return parse_change_log(data, offset)

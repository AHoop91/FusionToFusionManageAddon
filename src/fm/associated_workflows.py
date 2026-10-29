"""The workflows associated with an item: the workflow items (such as change orders) that reference it.

``GET /api/v3/workspaces/{ws}/items/{id}/views/2`` answers with a list, one entry per workflow item, giving its
current state and the last step of its workflow history.
"""

from typing import Any, Dict, List

from ..core.shapes import as_dict, dict_rows, dig
from .client import WORKSPACES, FmApiError, FmClient
from .pages import item_page

REFERENCES_VIEW = "2"   # the view of an item that lists the workflow items referencing it


def _text(value: Any) -> str:
    return str(value or "")


def _step(history: Any) -> Dict[str, str]:
    """When, by whom, and with which transition a workflow history entry was made, and its comments."""
    return {"date": _text(dig(history, "created")), "user": _text(dig(history, "user", "title")),
            "action": _text(dig(history, "workflowTransition", "title")), "comments": _text(dig(history, "comments"))}


def parse_associated_workflows(data: Any, base_url: str) -> List[Dict[str, Any]]:
    """The rows of the Associated Workflows tab from a view answer."""
    if data is None:   # 204: no workflow item references the item
        return []
    if not isinstance(data, list):
        raise FmApiError("Fusion Manage did not return the associated workflows of this item.")
    rows = []
    for entry in dict_rows(data):
        item = as_dict(entry.get("item"))
        if not item:
            continue
        state = dig(entry, "workflow-state", "title") or item.get("currentState")
        rows.append({"title": _text(item.get("title")), "state": _text(state),
                     "url": item_page(base_url, item), "last": _step(entry.get("last-workflow-history"))})
    return rows


class AssociatedWorkflowService:
    """Reads the associated workflows of an item through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str) -> List[Dict[str, Any]]:
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}/views/{REFERENCES_VIEW}")
        return parse_associated_workflows(data, self._client.base_url)

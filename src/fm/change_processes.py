"""The change processes an item is in: the workflow items (such as change orders) that reference it.

``GET /api/v3/workspaces/{ws}/items/{id}/views/2`` answers with a list, one entry per workflow item, giving its
current state and the last step of its workflow history.
"""

from typing import Any, Dict, List

from .client import WORKSPACES, FmApiError, FmClient
from .pages import item_page

REFERENCES_VIEW = "2"   # the view of an item that lists the workflow items referencing it


def _step(history: Any) -> Dict[str, str]:
    """When, by whom, and with which transition a workflow history entry was made, and its comments."""
    history = history if isinstance(history, dict) else {}
    user = history.get("user") if isinstance(history.get("user"), dict) else {}
    transition = history.get("workflowTransition") if isinstance(history.get("workflowTransition"), dict) else {}
    return {"date": str(history.get("created") or ""), "user": str(user.get("title") or ""),
            "action": str(transition.get("title") or ""), "comments": str(history.get("comments") or "")}


def parse_change_processes(data: Any, base_url: str) -> List[Dict[str, Any]]:
    """The rows of the Change Processes tab from a view answer."""
    if data is None:   # 204: no workflow item references the item
        return []
    if not isinstance(data, list):
        raise FmApiError("Fusion Manage did not return the change processes of this item.")
    rows = []
    for entry in data:
        item = entry.get("item") if isinstance(entry, dict) and isinstance(entry.get("item"), dict) else None
        if item is None:
            continue
        state = entry.get("workflow-state") if isinstance(entry.get("workflow-state"), dict) else {}
        rows.append({"title": str(item.get("title") or ""), "state": str(state.get("title") or item.get("currentState") or ""),
                     "url": item_page(base_url, item), "last": _step(entry.get("last-workflow-history"))})
    return rows


class ChangeProcessService:
    """Reads the change processes of an item through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str) -> List[Dict[str, Any]]:
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}/views/{REFERENCES_VIEW}")
        return parse_change_processes(data, self._client.base_url)

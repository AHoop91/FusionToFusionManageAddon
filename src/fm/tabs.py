"""The tabs of an item in Fusion Manage: their names, from the workspace, and how many entries each holds, from the item.
The names are only ever Fusion Manage's own: a tab the workspace does not list is not shown, and a failed read is an error.

``GET /api/v3/workspaces/{ws}/tabs`` lists the tabs of the workspace (``workspaceTabName``, and a ``name`` or else a ``key`` to show).
``GET /api/v3/workspaces/{ws}/items/{id}/tabs`` gives each tab's ``totalCount``, so the page can label its tabs without reading them.
"""

import time
from typing import Any, Dict, Set, Tuple

from .client import WORKSPACES, FmClient

CACHE_SECONDS = 300   # a workspace's tabs rarely change
# the permission that lets the user see each tab
TAB_PERMISSIONS = {"item": "view_items", "files": "view_attachments", "bom": "view_bom", "whereused": "view_where_used",
                   "workflows": "view_associated_workflow"}
# the tabs the page shows, by the name Fusion Manage gives them
TABS = {"item": "ITEM_DETAILS", "files": "PART_ATTACHMENTS", "bom": "BOM_LIST", "whereused": "BOM_WHERE_USED", "workflows": "WORKFLOW_REFERENCES"}
# a tab counts only the entries it lists: the Files tab lists the item's own files, not the ones related items bring (those are in the total)
COUNTED = {"PART_ATTACHMENTS": "PART_ATTACHMENTS/DIRECT_ATTACHMENTS"}


def parse_labels(data: Any) -> Dict[str, str]:
    """``{workspaceTabName: label}`` from the workspace's tab list."""
    labels = {}
    for tab in data if isinstance(data, list) else []:
        if isinstance(tab, dict) and tab.get("workspaceTabName"):
            label = str(tab.get("name") or tab.get("key") or "")
            if label:
                labels[str(tab["workspaceTabName"])] = label
    return labels


def parse_counts(data: Any) -> Dict[str, int]:
    """``{workspaceTabName: totalCount}`` from the item's tab counts, and ``{"TAB/SECTION": count}`` for each section a tab has."""
    counts = {}
    for tab in data.get("tabs") if isinstance(data, dict) and isinstance(data.get("tabs"), list) else []:
        if isinstance(tab, dict) and tab.get("name"):
            counts[str(tab["name"])] = int(tab.get("totalCount") or 0)
            for section in tab.get("sectionCounts") if isinstance(tab.get("sectionCounts"), list) else []:
                if isinstance(section, dict) and section.get("name"):
                    counts[f"{tab['name']}/{section['name']}"] = int(section.get("totalCount") or 0)
    return counts


class TabService:
    """Reads the names and counts of an item's tabs through an ``FmClient``."""

    _labels_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, str]]] = {}   # (tenant, workspace id) -> (read at, labels)

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str, held: Set[str]) -> Dict[str, Dict[str, Any]]:
        """``{"files": {"label", "count", "allowed"}, ...}`` for each tab the page shows that the workspace has; ``allowed`` is whether
        the user's permissions (``held``) let them see it. Raises ``FmApiError`` when the names or counts cannot be read."""
        labels = self._labels(workspace_id)
        counts = parse_counts(self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}/tabs"))
        return {key: {"label": labels[name], "count": counts.get(COUNTED.get(name, ""), counts.get(name, 0)), "allowed": TAB_PERMISSIONS[key] in held}
                for key, name in TABS.items() if name in labels}

    def _labels(self, workspace_id: str) -> Dict[str, str]:
        key = (self._client.tenant, workspace_id)
        cached = self._labels_cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        labels = parse_labels(self._client.get_json(f"{WORKSPACES}/{workspace_id}/tabs"))
        self._labels_cache[key] = (time.monotonic(), labels)
        return labels

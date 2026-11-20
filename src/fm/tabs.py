"""The tabs of an item in Fusion Manage: their names, from the workspace, and how many entries each holds, from the item.
The names are only ever Fusion Manage's own: a tab the workspace does not list is not shown, and a failed read is an error.

``GET /api/v3/workspaces/{ws}/tabs`` lists the tabs of the workspace (``workspaceTabName``, and a ``name`` or else a ``key`` to show).
``GET /api/v3/workspaces/{ws}/items/{id}/tabs`` gives each tab's ``totalCount``, so the page can label its tabs without reading them.
"""

from typing import Any, Dict, Set

from ..core.shapes import dict_rows, dig, whole
from .client import WORKSPACES, FmClient
from .ttl_cache import TtlCache

# the permission that lets the user see each tab
TAB_PERMISSIONS = {"item": "view_items", "files": "view_attachments", "bom": "view_bom", "whereused": "view_where_used",
                   "workflows": "view_associated_workflow", "changelog": "view_change_log"}
# the tabs the page shows, by the name Fusion Manage gives them
TABS = {"item": "ITEM_DETAILS", "files": "PART_ATTACHMENTS", "bom": "BOM_LIST", "whereused": "BOM_WHERE_USED", "workflows": "WORKFLOW_REFERENCES",
        "changelog": "PART_HISTORY"}
# the Grid tab of a workspace, which the page of a product shows but the Item panel does not
GRID_TAB = "PART_GRID"
# a tab counts only the entries it lists: the Files tab lists the item's own files, not the ones related items bring (those are in the total)
COUNTED = {"PART_ATTACHMENTS": "PART_ATTACHMENTS/DIRECT_ATTACHMENTS"}


def parse_labels(data: Any) -> Dict[str, str]:
    """``{workspaceTabName: label}`` from the workspace's tab list."""
    labels = {}
    for tab in dict_rows(data):
        label = str(tab.get("name") or tab.get("key") or "")
        if tab.get("workspaceTabName") and label:
            labels[str(tab["workspaceTabName"])] = label
    return labels


def parse_counts(data: Any) -> Dict[str, int]:
    """``{workspaceTabName: totalCount}`` from the item's tab counts, and ``{"TAB/SECTION": count}`` for each section a tab has."""
    counts: Dict[str, int] = {}
    for tab in dict_rows(dig(data, "tabs")):
        if not tab.get("name"):
            continue
        counts[str(tab["name"])] = whole(tab.get("totalCount"))
        for section in dict_rows(tab.get("sectionCounts")):
            if section.get("name"):
                counts[f"{tab['name']}/{section['name']}"] = whole(section.get("totalCount"))
    return counts


def _count_of(counts: Dict[str, int], name: str) -> int:
    """How many entries the tab ``name`` lists: what ``COUNTED`` says it lists when the answer has that, else its total, else none."""
    counted = COUNTED.get(name)
    return counts[counted] if counted in counts else counts.get(name, 0)


class TabService:
    """Reads the names and counts of an item's tabs through an ``FmClient``."""

    _labels_cache = TtlCache()   # (tenant, workspace id) -> labels; a workspace's tabs rarely change

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str, held: Set[str], with_grid: bool = False) -> Dict[str, Dict[str, Any]]:
        """``{"files": {"label", "count", "allowed"}, ...}`` for each tab the page shows that the workspace has; ``allowed`` is whether
        the user's permissions (``held``) let them see it. ``with_grid`` adds the Grid tab as ``"grid"`` when the workspace has one (a product's
        page shows it; the Item panel does not). Raises ``FmApiError`` when the names or counts cannot be read."""
        labels = self.labels(workspace_id)
        counts = self.counts(workspace_id, item_id)
        tabs = {key: {"label": labels[name], "count": counts.get(key, 0), "allowed": TAB_PERMISSIONS[key] in held}
                for key, name in TABS.items() if name in labels}
        if with_grid and GRID_TAB in labels:
            tabs["grid"] = {"label": labels[GRID_TAB], "count": counts["grid"], "allowed": True}
        return tabs

    def counts(self, workspace_id: str, item_id: str) -> Dict[str, int]:
        """``{"files": count, ...}``: how many entries each tab the page shows holds now (read afresh, not kept), and the Grid tab's as ``"grid"``."""
        counts = parse_counts(self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}/tabs"))
        return {**{key: _count_of(counts, name) for key, name in TABS.items()}, "grid": _count_of(counts, GRID_TAB)}

    @classmethod
    def forget(cls) -> None:
        """Drop the kept tab names, so the next read asks Fusion Manage again."""
        cls._labels_cache.clear()

    def labels(self, workspace_id: str) -> Dict[str, str]:
        """``{workspaceTabName: label}`` of the workspace's tabs (read once, then kept for a while). Raises ``FmApiError`` when they cannot be read."""
        key = (self._client.tenant, workspace_id)
        cached = self._labels_cache.get(key)
        if cached is not None:
            return cached
        return self._labels_cache.put(key, parse_labels(self._client.get_json(f"{WORKSPACES}/{workspace_id}/tabs")))

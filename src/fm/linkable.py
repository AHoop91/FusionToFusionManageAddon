"""Linkable items: the rows Fusion Manage offers for adding items to a Bill of Materials.

Adding an item to a BOM posts its linkable-items row back (see ``publish.bom_requests``); the Add Items picker
finds the items through the search API (see ``item_search``).
"""

from typing import Any, Dict

from .client import WORKSPACES

BOM_VIEW_ID = "5"   # the Bill of Materials view is always view 5


def linkable_row(workspace_id: str, parent: str, item: str) -> Dict[str, Any]:
    """The linkable-items row of ``item`` in the BOM view of ``parent``, as Fusion Manage answers it (``{{tenant}}`` is filled in when sent).

    ``parent`` and ``item`` are ids, or ``{{item:<number>}}`` markers of items a publish run creates (see ``publish.placeholders``)."""
    return {"__self__": f"{WORKSPACES}/{workspace_id}/items/{parent}/views/{BOM_VIEW_ID}/linkable-items/{item}",
            "urn": f"urn:adsk.plm:tenant.workspace.item.view.linkable-item:{{{{tenant}}}}.{workspace_id}.{parent}.{BOM_VIEW_ID}.{item}",
            "item": {"link": f"{WORKSPACES}/{workspace_id}/items/{item}",
                     "urn": f"urn:adsk.plm:tenant.workspace.item:{{{{tenant}}}}.{workspace_id}.{item}"}}

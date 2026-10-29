"""Linkable items: the rows Fusion Manage offers for adding items to a Bill of Materials.

Adding an item to a BOM posts its linkable-items row back (see ``publish.bom_requests``); the Add Items picker
finds the items through the search API (see ``item_search``).
"""

from typing import Any, Dict

from .client import WORKSPACES

BOM_VIEW_ID = "5"   # the Bill of Materials view is always view 5
TENANT = "{{tenant}}"   # the tenant code in an urn, filled in when the request is sent (see ``publish.placeholders``)


def item_link(workspace_id: str, item: str) -> str:
    """The API link of an item."""
    return f"{WORKSPACES}/{workspace_id}/items/{item}"


def item_urn(workspace_id: str, item: str) -> str:
    """The urn of an item, with the tenant to be filled in."""
    return f"urn:adsk.plm:tenant.workspace.item:{TENANT}.{workspace_id}.{item}"


def linkable_row(workspace_id: str, parent: str, item: str) -> Dict[str, Any]:
    """The linkable-items row of ``item`` in the BOM view of ``parent``, as Fusion Manage answers it (``{{tenant}}`` is filled in when sent).

    ``parent`` and ``item`` are ids, or ``{{item:<number>}}`` markers of items a publish run creates (see ``publish.placeholders``)."""
    return {"__self__": f"{item_link(workspace_id, parent)}/views/{BOM_VIEW_ID}/linkable-items/{item}",
            "urn": f"urn:adsk.plm:tenant.workspace.item.view.linkable-item:{TENANT}.{workspace_id}.{parent}.{BOM_VIEW_ID}.{item}",
            "item": {"link": item_link(workspace_id, item), "urn": item_urn(workspace_id, item)}}

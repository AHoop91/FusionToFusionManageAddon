"""Where things are in Fusion Manage's own web UI: the page of an item, or its files, built from an API link and the tenant."""

import re
from typing import Any, Dict

ITEM_LINK = re.compile(r"/workspaces/(\d+)/items/(\d+)")   # an item's API link: /api/v3/workspaces/<workspace>/items/<item>
_TENANT = re.compile(r"[:.]([^.:]+)\.\d+\.\d+$")   # urn:adsk.plm:tenant.workspace.item:TENANT.<workspace>.<item>
_FIELD_ID = re.compile(r"/fields/([^/]+)/?$")


def tenant_of(item: Dict[str, Any]) -> str:
    found = _TENANT.search(str(item.get("urn") or ""))
    return found.group(1) if found else ""


def page_url(base_url: str, tenant: str, workspace_id: str, item_id: str, page: str = "itemDetails", tab: str = "details") -> str:
    """The page of an item in Fusion Manage's own web UI: the Item tab, or (``page="attachments"``, ``tab="attachments"``) its files."""
    urn = f"urn`adsk,plm`tenant,workspace,item`{tenant},{workspace_id},{item_id}"
    return (f"{base_url}/plm/workspaces/{workspace_id}/items/{page}?view=full&tab={tab}&mode=view&itemId="
            + urn.replace("`", "%60").replace(",", "%2C"))


def link_page(base_url: str, tenant: str, link: str, page: str = "itemDetails", tab: str = "details") -> str:
    """The page of the item an API link points at ("" when it is not an item's link or there is no tenant or base address)."""
    found = ITEM_LINK.search(link)
    return page_url(base_url, tenant, found.group(1), found.group(2), page, tab) if found and tenant and base_url else ""


def item_page(base_url: str, item: Dict[str, Any], page: str = "itemDetails", tab: str = "details") -> str:
    """The page of an item as an answer describes it (its ``__self__`` or ``link`` and its ``urn``); "" when they are not understood."""
    return link_page(base_url, tenant_of(item), str(item.get("__self__") or item.get("link") or ""), page, tab)


def field_id(node: Any) -> str:
    """The id of a field reference (a dict with a link, or None for an empty matrix cell)."""
    if not isinstance(node, dict):
        return ""
    for key in ("__self__", "link", "urn"):
        match = _FIELD_ID.search(str(node.get(key) or ""))
        if match:
            return match.group(1)
    return ""

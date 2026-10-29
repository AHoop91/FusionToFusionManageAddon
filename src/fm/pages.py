"""Where things are in Fusion Manage's own web UI: the page of an item, or its files, built from an API link and the tenant."""

import re
from typing import Any

from ..core.shapes import as_dict

LINK_KEYS = ("__self__", "link", "urn")   # where an answer may name what it describes, in the order tried
ITEM_LINK = re.compile(r"/workspaces/(\d+)/items/(\d+)")   # an item's API link: /api/v3/workspaces/<workspace>/items/<item>
FIELD_ID = re.compile(r"/fields/([^/]+)/?$")   # a field's API link: .../fields/<field id>
_TENANT = re.compile(r"[:.]([^.:]+)\.\d+\.\d+$")   # urn:adsk.plm:tenant.workspace.item:TENANT.<workspace>.<item>


def tenant_of(item: Any) -> str:
    """The tenant code in the ``urn`` of an item as an answer describes it ("" when it has none)."""
    found = _TENANT.search(str(as_dict(item).get("urn") or ""))
    return found.group(1) if found else ""


def page_url(base_url: str, tenant: str, workspace_id: str, item_id: str, page: str = "itemDetails", tab: str = "details") -> str:
    """The page of an item in Fusion Manage's own web UI: the Item tab, or (``page="attachments"``, ``tab="attachments"``) its files."""
    urn = f"urn`adsk,plm`tenant,workspace,item`{tenant},{workspace_id},{item_id}"   # Fusion Manage's own page url escapes its backticks and commas
    return (f"{base_url}/plm/workspaces/{workspace_id}/items/{page}?view=full&tab={tab}&mode=view&itemId="
            + urn.replace("`", "%60").replace(",", "%2C"))


def link_page(base_url: str, tenant: str, link: str, page: str = "itemDetails", tab: str = "details") -> str:
    """The page of the item an API link points at ("" when it is not an item's link or there is no tenant or base address)."""
    found = ITEM_LINK.search(link)
    return page_url(base_url, tenant, found.group(1), found.group(2), page, tab) if found and tenant and base_url else ""


def item_page(base_url: str, item: Any, page: str = "itemDetails", tab: str = "details") -> str:
    """The page of an item as an answer describes it (its ``__self__`` or ``link`` and its ``urn``); "" when they are not understood."""
    link = as_dict(item).get("__self__") or as_dict(item).get("link") or ""
    return link_page(base_url, tenant_of(item), str(link), page, tab)


def field_id(node: Any) -> str:
    """The id of a field reference (a dict with a link, or None for an empty matrix cell)."""
    node = as_dict(node)
    for key in LINK_KEYS:
        match = FIELD_ID.search(str(node.get(key) or ""))
        if match:
            return match.group(1)
    return ""

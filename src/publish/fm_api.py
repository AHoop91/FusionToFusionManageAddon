"""Pieces shared by the Fusion Manage request builders.

Each request is ``{"method", "url", "body"}`` with a url relative to the Fusion Manage host.
They are drafts: the body shapes follow the Fusion Manage v3 API but have not been
checked against a tenant.
"""

from typing import Any, Dict

API = "/api/v3/workspaces"
LOOKUPS = "/api/v3/lookups/"


def field_entry(workspace_id: str, field_id: str, value: Any) -> Dict[str, Any]:
    """One field of an item body. A picklist option is sent as a link to it."""
    if isinstance(value, str) and value.startswith(LOOKUPS):
        value = {"link": value}
    return {"__self__": f"{API}/{workspace_id}/views/1/fields/{field_id}", "value": value}

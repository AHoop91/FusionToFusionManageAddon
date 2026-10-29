"""What the signed-in user may do in a Fusion Manage workspace.

``GET /api/v3/workspaces/{ws}/users/@me/permissions`` lists the permissions the user holds there, each with a ``name`` such as
``permission.shortname.view_bom``. They are used here by their short name (``view_bom``).
"""

from typing import Any, Iterable, List, Set

from ..core.shapes import dict_rows, dig
from .client import WORKSPACES, FmApiError, FmClient

PERMISSION_PREFIX = "permission.shortname."
VIEW_ITEMS = "view_items"   # without it nothing of the workspace can be seen
ATTACH_PERMISSIONS = (VIEW_ITEMS, "add_attachments", "edit_attachments")   # to find the record, attach a file, and give a file a new version
REFUSED = (401, 403)   # the statuses of a request the user is not allowed to make


def _short(name: str) -> str:
    """``permission.shortname.add_items`` as ``add_items``; a name without the prefix is as it is."""
    return name[len(PERMISSION_PREFIX):] if name.startswith(PERMISSION_PREFIX) else name


def parse_granted(data: Any) -> Set[str]:
    """Short permission names (``add_items``) in the answer of the permissions request."""
    names = (row.get("name") for row in dict_rows(dig(data, "permissions")))
    return {_short(name) for name in names if isinstance(name, str)}


def granted(client: FmClient, workspace_id: str) -> Set[str]:
    """The short names of the permissions the user holds in the workspace. Raises ``FmApiError`` when they cannot be read."""
    return parse_granted(client.get_json(f"{WORKSPACES}/{workspace_id}/users/@me/permissions"))


def title(permission: str) -> str:
    """``add_items`` -> ``Add Items``."""
    return permission.replace("_", " ").title()


def missing(required: Iterable[str], held: Set[str]) -> List[str]:
    """The ``required`` permissions that are not in ``held``, in order."""
    return [p for p in required if p not in held]


def denial(client: FmClient, workspace_id: str, required: Iterable[str], workspace_title: str, action: str = "publish to") -> str:
    """Why the user may not ``action`` the workspace ("" when their permissions include every one in ``required``).
    Raises ``FmApiError`` when the permissions cannot be read for any reason but being refused."""
    refusal = f"Insufficient permissions to {action} the {workspace_title} workspace."
    try:
        lacking = missing(required, granted(client, workspace_id))
    except FmApiError as exc:
        if exc.status in REFUSED:
            return refusal
        raise
    return f"{refusal} Missing: {', '.join(title(p) for p in lacking)}." if lacking else ""

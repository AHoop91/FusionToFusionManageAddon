"""What the signed-in user may do in a Fusion Manage workspace.

``GET /api/v3/workspaces/{ws}/users/@me/permissions`` lists the permissions the user holds there, each with a ``name`` such as
``permission.shortname.view_bom``. They are used here by their short name (``view_bom``).
"""

from typing import Any, Iterable, List, Set

from .client import WORKSPACES, FmApiError, FmClient

PERMISSION_PREFIX = "permission.shortname."
VIEW_ITEMS = "view_items"   # without it nothing of the workspace can be seen


def parse_granted(data: Any) -> Set[str]:
    """Short permission names (``add_items``) in the answer of the permissions request."""
    rows = data.get("permissions") if isinstance(data, dict) else None
    names = set()
    for row in rows if isinstance(rows, list) else []:
        name = row.get("name") if isinstance(row, dict) else None
        if isinstance(name, str):
            names.add(name[len(PERMISSION_PREFIX):] if name.startswith(PERMISSION_PREFIX) else name)
    return names


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
    try:
        lacking = missing(required, granted(client, workspace_id))
    except FmApiError as exc:
        if exc.status in (401, 403):
            return f"Insufficient permissions to {action} the {workspace_title} workspace."
        raise
    if not lacking:
        return ""
    return f"Insufficient permissions to {action} the {workspace_title} workspace. Missing: " + ", ".join(title(p) for p in lacking) + "."

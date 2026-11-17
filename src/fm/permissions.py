"""What the signed-in user may do in a Fusion Manage workspace.

``GET /api/v3/workspaces/{ws}/users/@me/permissions`` lists the permissions the user holds there, each with a ``name`` such as
``permission.shortname.view_bom``. They are used here by their short name (``view_bom``).
"""

from typing import Any, Iterable, List, Set

from ..core.shapes import dict_rows, dig
from ..core.i18n import t
from .client import WORKSPACES, FmApiError, FmClient

PERMISSION_PREFIX = "permission.shortname."
VIEW_ITEMS = "view_items"   # without it nothing of the workspace can be seen
ADD_ITEMS = "add_items"   # to create an item
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


def may(client: FmClient, workspace_id: str, permission: str) -> bool:
    """Whether the user holds ``permission`` in the workspace. When the permissions cannot be read (but for being refused) it is True:
    Fusion Manage still refuses what the user may not do, and the add-in must not take a right away on a failed read."""
    try:
        return permission in granted(client, workspace_id)
    except FmApiError as exc:
        return exc.status not in REFUSED


def title(permission: str) -> str:
    """``add_items`` -> ``Add Items``, in the language in use for the ones the add-in knows; the others are made from their name."""
    known = {
        "view_items": lambda: t("data.permission_view_items"),
        "add_items": lambda: t("data.permission_add_items"),
        "edit_items": lambda: t("data.permission_edit_items"),
        "view_bom": lambda: t("data.permission_view_bom"),
        "add_to_bom": lambda: t("data.permission_add_to_bom"),
        "edit_bom": lambda: t("data.permission_edit_bom"),
        "add_attachments": lambda: t("data.permission_add_attachments"),
        "edit_attachments": lambda: t("data.permission_edit_attachments"),
    }.get(permission)
    return known() if known else permission.replace("_", " ").title()


def missing(required: Iterable[str], held: Set[str]) -> List[str]:
    """The ``required`` permissions that are not in ``held``, in order."""
    return [p for p in required if p not in held]


def denial(client: FmClient, workspace_id: str, required: Iterable[str], workspace_title: str, action: str = "publish to") -> str:
    """Why the user may not ``action`` the workspace ("" when their permissions include every one in ``required``).
    Raises ``FmApiError`` when the permissions cannot be read for any reason but being refused."""
    refusal = {   # ``action`` is the English phrase callers give; each one the add-in uses has its own sentence
        "publish to": lambda: t("data.permission_refused_publish", workspace=workspace_title),
        "attach files to": lambda: t("data.permission_refused_attach", workspace=workspace_title),
    }.get(action, lambda: t("data.permission_refused_other", action=action, workspace=workspace_title))()
    try:
        lacking = missing(required, granted(client, workspace_id))
    except FmApiError as exc:
        if exc.status in REFUSED:
            return refusal
        raise
    return t("data.permission_missing", refusal=refusal, missing=", ".join(title(p) for p in lacking)) if lacking else ""

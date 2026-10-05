"""Fusion Manage workspace validation.

Validating a workspace id means:

* ``GET /api/v3/workspaces/{id}`` succeeds and the workspace is not deleted.
* ``GET /api/v3/workspaces/{id}/users/@me/permissions`` shows the signed-in
  user holds the permissions the workspace kind needs (view/add/edit items).
* Each option (BOM, STEP) is checked against the permissions it
  needs. An option the user cannot use is reported as blocked, with a reason,
  so the panel can switch it off.
* ``GET /api/v3/workspaces/{id}/fields`` supplies the field list for the
  mapping picker. Each fixed-list field's ``GET /api/v3/lookups/{name}``
  supplies the options offered for its static value.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceKind
from ..core.logging_setup import get_logger
from .client import FmApiError, FmClient

log = get_logger("fm.workspace")

PERMISSION_PREFIX = "permission.shortname."
OPTIONS_PAGE = 100   # picklist options requested per call
MAX_OPTIONS = 2000   # stop reading a picklist after this many options
READERS = 4          # picklists read at once


class WorkspaceService:
    """Validates workspace ids through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def validate(self, kind: WorkspaceKind, workspace_id: str) -> Dict[str, Any]:
        """Return ``{kind, valid, message, blocked}`` for one workspace id.

        ``blocked`` maps option id -> reason for options the user lacks the
        permissions for. It is only meaningful when ``valid`` is true.
        """
        result: Dict[str, Any] = {"kind": kind.kind_id, "valid": False, "message": "", "blocked": {}}
        if not workspace_id.isdigit():
            result["message"] = "Workspace ID must be a number."
            return result

        base = f"/api/v3/workspaces/{workspace_id}"
        try:
            workspace = self._client.get_json(base)
            if not isinstance(workspace, dict) or workspace.get("deleted"):
                result["message"] = f"Workspace {workspace_id} was not found or has been deleted."
                return result
            granted = self._granted(self._client.get_json(f"{base}/users/@me/permissions"))
        except FmApiError as exc:
            log.warning("Workspace %s validation failed: %s", workspace_id, exc)
            result["message"] = self._explain(exc, workspace_id)
            return result
        except AuthError as exc:
            result["message"] = f"Not signed in: {exc}"
            return result

        missing = [p for p in kind.required_permissions if p not in granted]
        if missing:
            result["message"] = (f"You need these permissions on '{workspace.get('name', workspace_id)}': "
                                 + ", ".join(self._title(p) for p in missing) + ".")
            return result

        for option in kind.options:
            lacking = [p for p in option.permissions if p not in granted]
            if lacking:
                result["blocked"][option.option_id] = (
                    "Not available: you lack " + ", ".join(self._title(p) for p in lacking) + ".")

        result["valid"] = True
        result["message"] = f"Workspace '{workspace.get('name', workspace_id)}' is valid."
        result["fields"], result["picklists"], result["fields_error"] = self._fields(base)
        return result

    def _fields(self, base: str) -> Any:
        """The workspace's fields for the mapping picker: ``([field], error)``.

        A failure here does not invalidate the workspace; the panel shows
        ``error`` in the empty field list instead.
        """
        try:
            data = self._client.get_json(f"{base}/fields")
        except (FmApiError, AuthError) as exc:
            log.warning("Could not load fields for %s: %s", base, exc)
            return [], {}, f"Could not load the workspace's fields: {exc}"
        rows = data.get("fields") if isinstance(data, dict) else data
        fields = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            field_id = str(row.get("__self__", "")).rstrip("/").rsplit("/", 1)[-1]
            if not field_id:
                continue
            kind = row.get("type") if isinstance(row.get("type"), dict) else {}
            # Fixed-list fields take one of the lookup's options. Fields that link to
            # another workspace (picklistFieldDefinition) and fields nobody can edit are left as text.
            pick = row.get("picklist")
            name = pick.rstrip("/").rsplit("/", 1)[-1] if isinstance(pick, str) else ""
            links = bool(row.get("picklistFieldDefinition"))
            link_lookup = name if links else ""   # the picklist of a field that links to another workspace
            lookup = "" if links or row.get("editability") == "NEVER" else name
            fields.append({"id": field_id, "title": str(row.get("name") or row.get("title") or field_id),
                           "type": str(kind.get("title", "")), "picklist": lookup,
                           "link_lookup": link_lookup})
        fields.sort(key=lambda f: f["title"].lower())
        names = sorted({f["picklist"] for f in fields if f["picklist"]})
        with ThreadPoolExecutor(max_workers=READERS) as pool:   # one lookup per picklist, several at once
            picklists = {n: o for n, o in zip(names, pool.map(self._options, names)) if o}
        for f in fields:   # a list that could not be loaded leaves its field as plain text
            if f["picklist"] not in picklists:
                f["picklist"] = ""
        return fields, picklists, ""

    def _options(self, lookup: str) -> List[Dict[str, str]]:
        """The options of one picklist as ``[{value: link, title}]``; empty if it cannot be read."""
        options: List[Dict[str, str]] = []
        offset = 0
        try:
            while offset < MAX_OPTIONS:
                data = self._client.get_json(
                    f"/api/v3/lookups/{lookup}?offset={offset}&limit={OPTIONS_PAGE}&filter=&asc=&desc=")
                items = data.get("items") if isinstance(data, dict) else None
                if not isinstance(items, list) or not items:
                    break
                for item in items:
                    if isinstance(item, dict) and item.get("link"):
                        options.append({"value": str(item["link"]), "title": str(item.get("title") or item["link"])})
                offset += len(items)
                if offset >= int(data.get("totalCount") or 0):
                    break
        except (FmApiError, AuthError, ValueError) as exc:
            log.warning("Could not load picklist %s: %s", lookup, exc)
            return []
        return options

    @staticmethod
    def _granted(data: Any) -> set:
        """Short permission names (``add_items``) the user holds."""
        rows = data.get("permissions") if isinstance(data, dict) else None
        names = set()
        for row in rows if isinstance(rows, list) else []:
            name = row.get("name") if isinstance(row, dict) else None
            if isinstance(name, str):
                names.add(name[len(PERMISSION_PREFIX):] if name.startswith(PERMISSION_PREFIX) else name)
        return names

    @staticmethod
    def _title(permission: str) -> str:
        """``add_items`` -> ``Add Items``."""
        return permission.replace("_", " ").title()

    @staticmethod
    def _explain(exc: FmApiError, workspace_id: str) -> str:
        if exc.status == 404:
            return f"Workspace {workspace_id} was not found."
        if exc.status in (401, 403):
            return f"You do not have access to workspace {workspace_id}."
        return str(exc)

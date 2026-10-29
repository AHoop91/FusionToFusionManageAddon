"""Fusion Manage workspace listing and validation.

``GET /api/v3/workspaces`` lists the workspaces; the ones whose ``type`` is the
revision controlled workspace type are offered for the Items workspace.

Validating a workspace id means:

* ``GET /api/v3/workspaces/{id}`` succeeds and the workspace is not deleted.
* ``GET /api/v3/workspaces/{id}/users/@me/permissions`` shows the signed-in
  user holds the permissions the workspace kind needs (view/add/edit items).
* ``GET /api/v3/workspaces/{id}/fields`` supplies the field list for the
  mapping picker. Each fixed-list field's ``GET /api/v3/lookups/{name}``
  supplies the options offered for its static value.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List
from urllib.parse import quote_plus

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceKind
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list, dict_rows, dig, rows_in
from .client import LOOKUPS, WORKSPACES, FmApiError, FmClient, last_segment
from .item_view import not_shown
from .permissions import missing, parse_granted, title

log = get_logger("fm.workspace")

OPTIONS_PAGE = 100   # picklist options requested per call
MAX_OPTIONS = 2000   # stop reading a picklist after this many options
READERS = 4          # picklists read at once
WORKSPACES_PAGE = 100   # workspaces requested per call
WORKSPACES_BULK = "application/vnd.autodesk.plm.workspaces.bulk+json"
REVISION_CONTROLLED_TYPE ="6"   # /api/v3/workspace-types/6: "Revision Controlled Workspace"


def _is_computed(row: Dict[str, Any]) -> bool:
    """Whether a field's value is worked out by Fusion Manage (a computed field) rather than entered: its ``formulaField`` flag."""
    return row.get("formulaField") is True or row.get("derived") is True


class WorkspaceService:
    """Validates workspace ids through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def revision_controlled(self) -> List[Dict[str, str]]:
        """The tenant's revision controlled workspaces as ``[{id, name}]``, sorted by name.

        Raises ``AuthError`` or ``FmApiError`` when the list cannot be read.
        """
        found: List[Dict[str, str]] = []
        seen: List[str] = []
        offset = 0
        while True:
            data = self._client.get_json(f"{WORKSPACES}?offset={offset}&limit={WORKSPACES_PAGE}", WORKSPACES_BULK)   # plain JSON leaves out each workspace's name and type
            rows = as_list(dig(data, "items"))
            if not rows:
                break
            for row in dict_rows(rows):
                if row.get("deleted") or row.get("controlled"):
                    continue   # a controlled workspace (Components, Drawings) is not one that holds items
                workspace_id = last_segment(row.get("__self__"))
                kind = row.get("type")   # a link, or an object holding one
                kind_id = last_segment(kind.get("link") or kind.get("__self__") if isinstance(kind, dict) else kind)
                seen.append(f"{row.get('name')}={kind_id or kind!r}")
                if workspace_id and kind_id == REVISION_CONTROLLED_TYPE:
                    found.append({"id": workspace_id, "name": str(row.get("name") or workspace_id)})
            offset += len(rows)
            if offset >= int(data.get("totalCount") or 0):
                break
        log.info("Workspace types: %s; revision controlled: %d", seen, len(found))
        found.sort(key=lambda w: w["name"].lower())
        return found

    def validate(self, kind: WorkspaceKind, workspace_id: str) -> Dict[str, Any]:
        """Return ``{kind, valid, message, ...}`` for one workspace id; a valid one also carries its fields and picklists."""
        result: Dict[str, Any] = {"kind": kind.kind_id, "valid": False, "message": ""}
        if not workspace_id.isdigit():
            result["message"] = "Workspace ID must be a number."
            return result

        base = f"{WORKSPACES}/{workspace_id}"
        try:
            workspace = self._client.get_json(base)
            if not isinstance(workspace, dict) or workspace.get("deleted"):
                result["message"] = f"Workspace {workspace_id} was not found or has been deleted."
                return result
            granted = parse_granted(self._client.get_json(f"{base}/users/@me/permissions"))
        except FmApiError as exc:
            log.warning("Workspace %s validation failed: %s", workspace_id, exc)
            result["message"] = self._explain(exc, workspace_id)
            return result
        except AuthError as exc:
            result["message"] = f"Not signed in: {exc}"
            return result

        lacking = missing(kind.required_permissions, granted)
        if lacking:
            result["message"] = (f"You need these permissions on '{workspace.get('name', workspace_id)}': "
                                 + ", ".join(title(p) for p in lacking) + ".")
            return result

        result["valid"] = True
        result["message"] = f"Workspace '{workspace.get('name', workspace_id)}' is valid."
        result["fields"], result["picklists"], result["fields_error"] = self._fields(base)
        return result

    def _fields(self, base: str) -> Any:
        """The workspace's fields for the mapping picker: ``([field], {lookup: options}, error)``.

        A failure here does not invalidate the workspace; the panel shows
        ``error`` in the empty field list instead.
        """
        fields, error = self.fields(base)
        if error:
            return [], {}, error
        names = sorted({f["picklist"] for f in fields if f["picklist"]})
        with ThreadPoolExecutor(max_workers=READERS) as pool:   # one lookup per picklist, several at once
            picklists = {n: o for n, o in zip(names, pool.map(self.options, names)) if o}
        for f in fields:   # a list that could not be loaded leaves its field as plain text
            if f["picklist"] not in picklists:
                f["picklist"] = ""
        return fields, picklists, ""

    def fields(self, base: str) -> Any:
        """The workspace's fields, without their picklist options: ``([{id, title, type, picklist, link_lookup, shown, computed}], error)`` (``shown``: not hidden on items; ``computed``: worked out by Fusion Manage)."""
        try:
            data = self._client.get_json(f"{base}/fields")
        except (FmApiError, AuthError) as exc:
            log.warning("Could not load fields for %s: %s", base, exc)
            return [], f"Could not load the workspace's fields: {exc}"
        fields = []
        for row in rows_in(data, "fields"):
            field_id = last_segment(row.get("__self__"))
            if not field_id:
                continue
            kind = as_dict(row.get("type"))
            # Fixed-list fields take one of the lookup's options. Fields that link to
            # another workspace (picklistFieldDefinition) and fields nobody can edit are left as text.
            pick = row.get("picklist")
            name = last_segment(pick)
            links = bool(row.get("picklistFieldDefinition"))
            link_lookup = name if links else ""   # the picklist of a field that links to another workspace
            lookup = "" if links or row.get("editability") == "NEVER" else name
            fields.append({"id": field_id, "title": str(row.get("name") or row.get("title") or field_id),
                           "type": str(kind.get("title", "")), "picklist": lookup,
                           "link_lookup": link_lookup, "shown": not not_shown(row, set()),
                           "computed": _is_computed(row)})
        fields.sort(key=lambda f: f["title"].lower())
        return fields, ""

    def filterable_fields(self, base: str) -> List[Dict[str, Any]]:
        """The fields an item search can be filtered by: those shown on items and not computed. Raises ``FmApiError`` when they cannot be read."""
        fields, error = self.fields(base)
        if error:
            raise FmApiError(error)
        return [f for f in fields if f["shown"] and not f["computed"]]

    def options_page(self, lookup: str, offset: int, limit: int, text: str = "") -> Dict[str, Any]:
        """One page of a picklist: ``{"options": [{value, title}], "total", "raw"}``, narrowed to titles matching ``text``.

        ``raw`` is how many options the page held (where the next page starts)."""
        data = self._client.get_json(
            f"{LOOKUPS}/{lookup}?offset={max(0, int(offset))}&limit={int(limit)}&filter={quote_plus(text.strip())}&asc=&desc=")
        rows = as_list(dig(data, "items"))
        options = [{"value": str(i["link"]), "title": str(i.get("title") or i["link"])} for i in dict_rows(rows) if i.get("link")]
        total = int(as_dict(data).get("totalCount") or 0)
        return {"options": options, "total": max(total, offset + len(rows)) if rows else total, "raw": len(rows)}

    def options(self, lookup: str) -> List[Dict[str, str]]:
        """The options of one picklist as ``[{value: link, title}]``; empty if it cannot be read."""
        options: List[Dict[str, str]] = []
        offset = 0
        try:
            while offset < MAX_OPTIONS:
                data = self._client.get_json(
                    f"{LOOKUPS}/{lookup}?offset={offset}&limit={OPTIONS_PAGE}&filter=&asc=&desc=")
                items = as_list(dig(data, "items"))
                if not items:
                    break
                for item in dict_rows(items):
                    if item.get("link"):
                        options.append({"value": str(item["link"]), "title": str(item.get("title") or item["link"])})
                offset += len(items)
                if offset >= int(data.get("totalCount") or 0):
                    break
        except (FmApiError, AuthError, ValueError) as exc:
            log.warning("Could not load picklist %s: %s", lookup, exc)
            return []
        return options

    @staticmethod
    def _explain(exc: FmApiError, workspace_id: str) -> str:
        if exc.status == 404:
            return f"Workspace {workspace_id} was not found."
        if exc.status in (401, 403):
            return f"You do not have access to workspace {workspace_id}."
        return str(exc)

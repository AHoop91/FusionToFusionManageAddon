"""Fusion Manage workspaces: which ones can hold items, whether the user may use one, and the fields and picklists it offers.

``GET /api/v3/workspaces`` lists the workspaces; the ones whose ``type`` is the revision controlled workspace type are offered for the
Items workspace.

Validating a workspace id means:

* ``GET /api/v3/workspaces/{id}`` succeeds and the workspace is not deleted.
* ``GET /api/v3/workspaces/{id}/users/@me/permissions`` shows the signed-in user holds the permissions the workspace kind needs
  (view/add/edit items).

A valid workspace also gives the mapping picker its fields (``GET /api/v3/workspaces/{id}/fields``) and, for each fixed-list field, the
options offered for its static value (``GET /api/v3/lookups/{name}``).
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote_plus

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceKind
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list, dict_rows, dig, rows_in, whole
from .client import LOOKUPS, WORKSPACES, FmApiError, FmClient, last_segment
from .item_view import not_shown
from .permissions import REFUSED, missing, parse_granted, title

log = get_logger("fm.workspace")

OPTIONS_PAGE = 100   # picklist options requested per call
MAX_OPTIONS = 2000   # stop reading a picklist after this many options
READERS = 4          # picklists read at once
WORKSPACES_PAGE = 100   # workspaces requested per call
MAX_WORKSPACES = 2000   # stop reading the list of workspaces after this many
WORKSPACES_BULK = "application/vnd.autodesk.plm.workspaces.bulk+json"
REVISION_CONTROLLED_TYPE = "6"   # /api/v3/workspace-types/6: "Revision Controlled Workspace"

Field = Dict[str, Any]   # a workspace field as the mapping picker takes it (see ``_field``)
Options = List[Dict[str, str]]   # ``[{value: link, title}]``


def _type_id(row: Dict[str, Any]) -> str:
    """The id of a workspace's type ("" if it names none): ``type`` is a link, or an object holding one."""
    kind = row.get("type")
    return last_segment(kind.get("link") or kind.get("__self__") if isinstance(kind, dict) else kind)


def _option(item: Dict[str, Any]) -> Dict[str, str]:
    """``{value: link, title}`` of a picklist option row."""
    return {"value": str(item["link"]), "title": str(item.get("title") or item["link"])}


def _field(row: Dict[str, Any], field_id: str) -> Field:
    """The picker's description of a workspace field.

    A fixed-list field takes one of its lookup's options. A field that links to another workspace (``picklistFieldDefinition``) and a field
    nobody can edit are left as text; the first keeps its lookup as ``link_lookup``. ``shown`` is whether the field is shown on items and
    ``computed`` whether Fusion Manage works its value out."""
    lookup_name = last_segment(row.get("picklist"))
    links = bool(row.get("picklistFieldDefinition"))
    return {"id": field_id, "title": str(row.get("name") or row.get("title") or field_id),
            "type": str(as_dict(row.get("type")).get("title") or ""),
            "picklist": "" if links or row.get("editability") == "NEVER" else lookup_name,
            "link_lookup": lookup_name if links else "", "shown": not not_shown(row, set()), "computed": _is_computed(row)}


def _is_computed(row: Dict[str, Any]) -> bool:
    """Whether a field's value is worked out by Fusion Manage (a computed field) rather than entered: its ``formulaField`` flag."""
    return row.get("formulaField") is True or row.get("derived") is True


def _verdict(kind: WorkspaceKind, valid: bool, message: str) -> Dict[str, Any]:
    """The outcome of validating a workspace of ``kind``."""
    return {"kind": kind.kind_id, "valid": valid, "message": message}


def _explain(exc: FmApiError, workspace_id: str) -> str:
    """Why reading the workspace failed, in words for the user."""
    if exc.status == 404:
        return f"Workspace {workspace_id} was not found."
    if exc.status in REFUSED:
        return f"You do not have access to workspace {workspace_id}."
    return str(exc)


class WorkspaceService:
    """Lists and validates workspaces, and reads their fields and picklists, through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def _rows(self, path_at: Callable[[int], str], cap: int, accept: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """The rows of a paged list, read a page at a time as they are asked for: until the list's total is reached, a page comes back
        empty, or ``cap`` rows have been read. ``path_at(offset)`` is the address of the page that starts at ``offset``."""
        offset = 0
        while offset < cap:
            path = path_at(offset)
            data = self._client.get_json(path) if accept is None else self._client.get_json(path, accept)
            rows = as_list(dig(data, "items"))
            if not rows:
                return
            yield from dict_rows(rows)
            offset += len(rows)   # the rows the page held, whether or not each is a usable object: that is where the next page starts
            if offset >= whole(dig(data, "totalCount")):
                return

    def revision_controlled(self) -> List[Dict[str, str]]:
        """The tenant's revision controlled workspaces as ``[{id, name}]``, sorted by name.

        Raises ``AuthError`` or ``FmApiError`` when the list cannot be read.
        """
        found: List[Dict[str, str]] = []
        seen: List[str] = []
        # the bulk form: plain JSON leaves out each workspace's name and type
        rows = self._rows(lambda offset: f"{WORKSPACES}?offset={offset}&limit={WORKSPACES_PAGE}", MAX_WORKSPACES, WORKSPACES_BULK)
        for row in rows:
            if row.get("deleted") or row.get("controlled"):
                continue   # a controlled workspace (Components, Drawings) is not one that holds items
            workspace_id, kind_id = last_segment(row.get("__self__")), _type_id(row)
            seen.append(f"{row.get('name')}={kind_id or row.get('type')!r}")
            if workspace_id and kind_id == REVISION_CONTROLLED_TYPE:
                found.append({"id": workspace_id, "name": str(row.get("name") or workspace_id)})
        log.info("Workspace types: %s; revision controlled: %d", seen, len(found))
        found.sort(key=lambda w: w["name"].lower())
        return found

    def validate(self, kind: WorkspaceKind, workspace_id: str) -> Dict[str, Any]:
        """``{kind, valid, message}`` for one workspace id; a valid one also carries its ``fields``, ``picklists`` and ``fields_error``."""
        if not workspace_id.isdigit():   # the id goes into an address: nothing but digits may
            return _verdict(kind, False, "Workspace ID must be a number.")
        base = f"{WORKSPACES}/{workspace_id}"
        try:
            workspace = self._client.get_json(base)
            if not isinstance(workspace, dict) or workspace.get("deleted"):
                return _verdict(kind, False, f"Workspace {workspace_id} was not found or has been deleted.")
            granted = parse_granted(self._client.get_json(f"{base}/users/@me/permissions"))
        except FmApiError as exc:
            log.warning("Workspace %s validation failed: %s", workspace_id, exc)
            return _verdict(kind, False, _explain(exc, workspace_id))
        except AuthError as exc:
            return _verdict(kind, False, f"Not signed in: {exc}")

        name = str(workspace.get("name") or workspace_id)
        lacking = missing(kind.required_permissions, granted)
        if lacking:
            return _verdict(kind, False, f"You need these permissions on '{name}': {', '.join(title(p) for p in lacking)}.")
        fields, picklists, fields_error = self._fields_and_picklists(base)
        return {**_verdict(kind, True, f"Workspace '{name}' is valid."), "fields": fields, "picklists": picklists, "fields_error": fields_error}

    def _fields_and_picklists(self, base: str) -> Tuple[List[Field], Dict[str, Options], str]:
        """The workspace's fields for the mapping picker: ``([field], {lookup: options}, error)``.

        A failure here does not invalidate the workspace; the panel shows ``error`` in the empty field list instead.
        """
        fields, error = self.fields(base)
        if error:
            return [], {}, error
        lookups = sorted({field["picklist"] for field in fields if field["picklist"]})
        with ThreadPoolExecutor(max_workers=READERS) as pool:   # one lookup per picklist, several at once
            loaded = {lookup: options for lookup, options in zip(lookups, pool.map(self.options, lookups)) if options}
        for field in fields:   # a list that could not be loaded leaves its field as plain text (the field dicts are ours: made by ``fields``)
            if field["picklist"] not in loaded:
                field["picklist"] = ""
        return fields, loaded, ""

    def fields(self, base: str) -> Tuple[List[Field], str]:
        """The workspace's fields, without their picklist options, by title: ``([field], error)`` (see ``_field``).
        ``error`` says why they could not be read, and is "" when they were."""
        try:
            data = self._client.get_json(f"{base}/fields")
        except (FmApiError, AuthError) as exc:
            log.warning("Could not load fields for %s: %s", base, exc)
            return [], f"Could not load the workspace's fields: {exc}"
        fields = [_field(row, field_id) for row in rows_in(data, "fields") if (field_id := last_segment(row.get("__self__")))]
        fields.sort(key=lambda f: f["title"].lower())
        return fields, ""

    def filterable_fields(self, base: str) -> List[Field]:
        """The fields an item search can be filtered by: those shown on items and not computed. Raises ``FmApiError`` when they cannot be read."""
        fields, error = self.fields(base)
        if error:
            raise FmApiError(error)
        return [f for f in fields if f["shown"] and not f["computed"]]

    def options_page(self, lookup: str, offset: int, limit: int, text: str = "") -> Dict[str, Any]:
        """One page of a picklist: ``{"options": [{value, title}], "total", "raw"}``, narrowed to titles matching ``text``.

        ``raw`` is how many options the page held (where the next page starts)."""
        offset = max(0, whole(offset))
        data = self._client.get_json(f"{LOOKUPS}/{lookup}?offset={offset}&limit={whole(limit)}&filter={quote_plus(text.strip())}&asc=&desc=")
        rows = as_list(dig(data, "items"))
        total = whole(dig(data, "totalCount"))
        if rows:
            total = max(total, offset + len(rows))   # a total that lags behind what was just served would end the paging early
        return {"options": [_option(row) for row in dict_rows(rows) if row.get("link")], "total": total, "raw": len(rows)}

    def options(self, lookup: str) -> Options:
        """The options of one picklist; empty if it cannot be read."""
        try:
            rows = self._rows(lambda offset: f"{LOOKUPS}/{lookup}?offset={offset}&limit={OPTIONS_PAGE}&filter=&asc=&desc=", MAX_OPTIONS)
            return [_option(row) for row in rows if row.get("link")]
        except (FmApiError, AuthError) as exc:
            log.warning("Could not load picklist %s: %s", lookup, exc)
            return []

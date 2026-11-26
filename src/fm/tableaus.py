"""The views (tableaus) of a Fusion Manage workspace, and the rows of a view.

* ``GET /api/v3/workspaces/{id}/tableaus`` lists the views.
* ``GET /api/v3/workspaces/{id}/tableaus/{view}`` with the ``META`` type describes one: its columns in order, each with the filters it takes
  (and the filters applied to it). The same address without it gives the rows.
* ``PUT`` of that description to the same address saves it: the filters of a view are the ``appliedFilters`` of its columns
  (``{"matchRule": "ALL", "filters": [{"type": <filter type link>, "value": ...}]}``). A view is shared, so this changes it for everyone.
* ``POST`` to ``/api/v3/workspaces/{id}/tableaus`` makes a view (``{"name", "columns", "isDefault"}``; its address comes back in ``Location``).
* ``PUT`` of the description with a new ``name`` renames a view.
* ``DELETE`` of ``/api/v3/workspaces/{id}/tableaus/{view}`` deletes a view.
* ``GET /api/v3/workspaces/{id}/tableaus`` with the ``META`` type lists the fields a view can be filtered by, each with its title: the
  rows name their fields by id only, so these are the column titles.
* ``GET /api/v3/workspaces/{id}/tableaus/{view}?page=1&size=50`` gives the rows of a view, a page at a time.

The list of views is ``{"tableaus": [{"link", "title"}]}``; a page of rows is ``{"total", "items": [{"item": {"link"}, "fields": [{"id", "value",
"type"}]}]}``. An answer is logged by its size only; its content goes into a verbose log (``log_body``).
"""

import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from ..core.logging_setup import endpoint, get_logger, log_body
from ..core.shapes import as_dict, dict_rows, dig, rows_in, whole
from .client import WORKSPACES, FmApiError, FmClient, id_of, last_segment
from .item_view import IMAGE, load_image
from .items import display_text
from .pages import field_id, item_id_of
from .ttl_cache import TtlCache

log = get_logger("fm.tableaus")

META = "application/vnd.autodesk.plm.meta+json"   # asks for the fields a view can be filtered by, not the views
DEFAULT_SIZE = 50
MAX_SIZE = 200
MATCH_RULES = ("ALL", "ANY")   # every filter must hold, or any one of them
FILTER_TYPE_PREFIX = "/api/v3/filter-types/"
MAX_FILTER_VALUE = 500
MAX_FILTERS = 20
MAX_COLUMNS = 100
MAX_VIEW_NAME = 30   # the longest name Fusion Manage keeps for a view
ANY_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
FIELD_KEY = re.compile(r"views/\d+/fields/[^/]+$")
PICTURE_LINK = re.compile(r"/api/v[23]/workspaces/(\d+)/items/\d+/field-values/[A-Z0-9_]+/image/\d+")


def parse_views(data: Any) -> List[Dict[str, str]]:
    """``[{"id", "name"}]`` of a list of views. Views of one name are told apart by their id."""
    views = []
    for row in rows_in(data, "tableaus"):
        view_id = id_of(row)
        if view_id:
            views.append({"id": view_id, "name": str(row.get("title") or view_id)})
    names = Counter(v["name"] for v in views)
    return [{**v, "name": f"{v['name']} ({v['id']})"} if names[v["name"]] > 1 else v for v in views]


def field_key(node: Any) -> str:
    """What names a field among all the workspace's: ``views/1/fields/TITLE`` (two sections can both have a ``TITLE``); the bare id if the link
    has no such tail."""
    match = FIELD_KEY.search(str(as_dict(node).get("__self__") or ""))
    return match.group(0) if match else field_id(node)


def _filters_of(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"id": str(f.get("link") or ""), "name": str(f.get("name") or ""), "takes_value": bool(f.get("allowValue")), "kind": str(f.get("valueType") or "")}
            for f in dict_rows(entry.get("applicableFilters")) if f.get("link")]


def parse_available(data: Any) -> List[Dict[str, Any]]:
    """``[{"key", "title", "group", "multiple", "filters": [...]}]``: every field a view can be filtered by, as the answer that lists them gives
    them, by section (``group``) in the order Fusion Manage shows the sections."""
    found = []
    for entry in dict_rows(data):
        node = as_dict(entry.get("field"))
        key = field_key(node)
        if not key:
            continue
        group = as_dict(entry.get("group"))
        found.append({"key": key, "title": str(node.get("title") or key), "group": str(group.get("displayName") or group.get("name") or ""),
                      "order": whole(group.get("displayOrder")), "multiple": bool(entry.get("allowMultipleFilters")), "filters": _filters_of(entry)})
    found.sort(key=lambda f: f["order"])   # stable: the fields of a section stay in their order
    for f in found:
        del f["order"]
    return found


def parse_titles(data: Any) -> Dict[str, str]:
    """``{field id: title}`` from the answer that lists the fields a view can be filtered by (each entry holds a ``field``)."""
    titles = {}
    for entry in dict_rows(data):
        node = as_dict(entry.get("field"))
        key = field_id(node)
        if key and node.get("title"):
            titles[key] = str(node["title"])
    return titles


def parse_columns(data: Any) -> List[Dict[str, Any]]:
    """``[{"id", "title", "multiple", "filters": [{"id", "name", "takes_value", "kind"}], "applied": {"match", "filters": [{"type", "value"}]}}]``:
    the columns of a view as it describes itself, in the order it shows them. ``multiple`` is whether the column takes more than one filter;
    ``id`` of a filter is its link, and ``type`` of an applied one is the link of the filter it uses."""
    entries = dict_rows(as_dict(data).get("columns"))
    found = []
    for entry in sorted(entries, key=lambda e: whole(e.get("displayOrder"))):
        node = as_dict(entry.get("field"))
        key = field_id(node)
        if not key:
            continue
        filters = _filters_of(entry)
        applied = as_dict(entry.get("appliedFilters"))
        match = "ANY" if str(applied.get("matchRule") or "").upper() == "ANY" else "ALL"
        used = [{"type": str(f.get("type") or ""), "value": "" if f.get("value") is None else str(f.get("value"))}
                for f in dict_rows(applied.get("filters")) if f.get("type")]
        found.append({"id": key, "key": field_key(node), "title": str(node.get("title") or key), "multiple": bool(entry.get("allowMultipleFilters")), "filters": filters,
                      "applied": {"match": match, "filters": used}})
    return found


def _cells(row: Dict[str, Any], titles: Dict[str, str]) -> Dict[str, Any]:
    """``{column key: (title, text, kind, markup)}`` of one row, from its list of fields (named by ``id``; ``titles`` says what each is called).
    ``kind`` is ``image`` for a picture (``text`` is then its id), ``markup`` the formatted text of a field that holds
    HTML (a formula's badges and bars; it arrives escaped), else ``""``."""
    cells: Dict[str, Any] = {}
    for node in dict_rows(row.get("fields")):
        key = str(node.get("id") or "")
        if not key:
            continue
        text = display_text(node.get("value"))
        decoded = html.unescape(text)
        markup = decoded if ANY_TAG.search(decoded) else ""
        kind = "image" if dig(node, "type", "title") == IMAGE else "text"
        cells[key] = (titles.get(key, key), ANY_TAG.sub("", decoded) if markup else text, kind, markup)
    return cells


def parse_rows(data: Any, titles: Dict[str, str] = None) -> Dict[str, Any]:
    """``{"columns": [{"id", "title", "kind"}], "rows": [{"id", "cells": {column id: text}, "html": {column id: markup}}], "total", "raw"}`` of a page of a view.

    The columns are the ones the rows hold, in the order they first appear, named by ``titles`` (``{field id: title}``) where it has them. ``raw`` is how many rows the page held; ``total`` is as the
    answer counts them (0 when it says nothing). ``html`` holds only the cells that have formatting; the page shows it through its own sanitiser."""
    node = as_dict(data)
    rows = rows_in(data, "items")
    columns: Dict[str, Dict[str, str]] = {}
    found = []
    for row in rows:
        cells = _cells(row, titles or {})
        for key, (title, _, kind, _) in cells.items():
            columns.setdefault(key, {"id": key, "title": title, "kind": kind})
        found.append({"id": item_id_of(as_dict(row.get("item"))), "cells": {key: c[1] for key, c in cells.items()},
                      "html": {key: c[3] for key, c in cells.items() if c[3]}})
    total = whole(node.get("total"))
    return {"columns": list(columns.values()), "rows": found, "total": total, "raw": len(rows)}


def _entry_for(column_id: str, entries: List[Any], offered: Any) -> Dict[str, Any]:
    """The column of the view that ``column_id`` (a field key, or a bare field id) names. A field the view does not show yet is taken from
    ``offered`` (what ``offered()`` gives: read only if needed) and joins the view as its last column. Raises ``FmApiError`` when there is no such field."""
    for entry in dict_rows(entries):
        node = as_dict(entry.get("field"))
        if column_id == field_key(node) or ("/" not in column_id and column_id == field_id(node)):
            return entry
    known = next((o for o in dict_rows(offered()) if field_key(as_dict(o.get("field"))) == column_id), None)
    if known is None:
        raise FmApiError("The view has no such column.")
    entry = {"field": known.get("field"), "displayOrder": max([whole(e.get("displayOrder")) for e in dict_rows(entries)] or [-1]) + 1,
             "allowMultipleFilters": bool(known.get("allowMultipleFilters")), "applicableFilters": known.get("applicableFilters") or []}
    entries.append(entry)
    return entry


def _chosen_filters(entry: Dict[str, Any], filters: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """``filters`` as the column ``entry`` takes them (``{"type", "value"}``, no value where the filter takes none). Raises ``FmApiError`` when one is
    not a filter the column takes, lacks the value it needs, or the column takes one filter only and gets more."""
    takes = {str(f.get("link")): bool(f.get("allowValue")) for f in dict_rows(entry.get("applicableFilters")) if f.get("link")}
    if len(filters) > 1 and not entry.get("allowMultipleFilters"):
        raise FmApiError("The column takes one filter only.")
    return [_chosen_filter(given, takes) for given in dict_rows(filters)]


def _chosen_filter(given: Dict[str, Any], takes: Dict[str, bool]) -> Dict[str, str]:
    """``given`` as the column takes it. ``takes`` says, for each filter the column takes, whether it needs a value. Raises ``FmApiError`` when the
    column does not take the filter or the filter lacks its value."""
    kind = str(given.get("type") or "")
    if not kind.startswith(FILTER_TYPE_PREFIX) or kind not in takes:
        raise FmApiError("The column does not take that filter.")
    value = str(given.get("value") or "").strip()[:MAX_FILTER_VALUE]
    if takes[kind] and not value:
        raise FmApiError("A filter needs a value.")
    return {"type": kind, "value": value} if takes[kind] else {"type": kind}


def _understood_change(change: Dict[str, Any]) -> Tuple[str, str, List[Dict[str, Any]]]:
    """``(column, match rule, filters)`` of one change of a view's filters. Raises ``FmApiError`` when the match rule is not one Fusion Manage has or the
    filters are not a list of at most ``MAX_FILTERS``."""
    filters = change.get("filters")
    match = str(change.get("match") or "ALL").upper()
    if match not in MATCH_RULES or not isinstance(filters, list) or len(filters) > MAX_FILTERS:
        raise FmApiError("The filters are not understood.")
    return str(change.get("column") or ""), match, filters


def _view_path(workspace_id: str, view_id: str) -> str:
    """The address of a view; its id goes into the address, so nothing but digits may be one."""
    if not view_id.isdigit():
        raise FmApiError("The view is not a number.")
    return f"{WORKSPACES}/{workspace_id}/tableaus/{view_id}"


def _checked_name(name: Any) -> str:
    """``name`` trimmed. Raises ``FmApiError`` when it is empty or longer than Fusion Manage keeps."""
    name = str(name or "").strip()
    if not name or len(name) > MAX_VIEW_NAME:
        raise FmApiError(f"A view needs a name of at most {MAX_VIEW_NAME} characters.")
    return name


def _checked_columns(columns: Any) -> List[Any]:
    """``columns`` when it is a list of one to ``MAX_COLUMNS`` keys. Raises ``FmApiError`` otherwise."""
    if not isinstance(columns, list) or not 0 < len(columns) <= MAX_COLUMNS:
        raise FmApiError("A view needs at least one column.")
    return columns


class TableauService:
    """Reads the views of a workspace and their rows through an ``FmClient``."""

    _meta = TtlCache()   # (tenant, workspace id) -> the answer that lists the fields a view can be filtered by; a workspace's fields rarely change

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def _read(self, label: str, path: str, accept: str = "application/json") -> Any:
        data = self._client.get_json(path, accept)
        log.info("%s: GET %s answered (%d characters)", label, endpoint(path), len(str(data)))
        log_body(log, label, data, f"GET {endpoint(path)}")
        return data

    def _fields_meta(self, workspace_id: str, fresh: bool = False) -> Any:
        """The answer that lists the fields a view of the workspace can be filtered by: read once, then kept. Raises ``FmApiError``."""
        key = (self._client.tenant, workspace_id)
        cached = None if fresh else self._meta.get(key)
        if cached is not None:
            return cached
        return self._meta.put(key, self._read("Fields a view can be filtered by", f"{WORKSPACES}/{workspace_id}/tableaus", META))

    def views(self, workspace_id: str) -> Dict[str, Any]:
        """``{"views": [{"id", "name"}]}``: the views of the workspace. Raises ``FmApiError`` when they cannot be read."""
        views = parse_views(self._read("Views", f"{WORKSPACES}/{workspace_id}/tableaus"))
        self._field_titles(workspace_id, fresh=True)   # read again whenever the views are, so a renamed field shows (and the fields are then at hand)
        return {"views": views}

    def _field_titles(self, workspace_id: str, fresh: bool = False) -> Dict[str, str]:
        """``{field id: title}`` of the workspace's fields. Raises ``FmApiError`` when they cannot be read."""
        return parse_titles(self._fields_meta(workspace_id, fresh))

    def columns(self, workspace_id: str, view_id: str) -> Dict[str, Any]:
        """``{"columns": [...]}`` as ``parse_columns`` gives them: what a view shows, known before any of its rows are read. Raises ``FmApiError``."""
        return {"columns": parse_columns(self._read("Columns of a view", _view_path(workspace_id, view_id), META))}

    def available(self, workspace_id: str) -> Dict[str, Any]:
        """``{"fields": [...]}`` as ``parse_available`` gives them: everything a view of the workspace can be filtered by. Raises ``FmApiError``."""
        return {"fields": parse_available(self._fields_meta(workspace_id))}

    def save_view_filters(self, workspace_id: str, view_id: str, changes: List[Dict[str, Any]], columns: Any = None) -> Dict[str, Any]:
        """Make each change's ``filters`` (``[{"type", "value"}]``; none clears them) the filters of its column of the view, saving the view once,
        and answer its columns as ``columns`` does. A change is ``{"column", "match", "filters"}``. The view is read fresh and written back whole
        with only those columns changed. When ``columns`` (the keys of the columns to show, in order) is given the view shows exactly those, in
        that order, in the same save. Raises ``FmApiError`` when a filter is not one its column takes, a column is not one the workspace has, or
        the view cannot be read or saved; nothing is saved then."""
        base = _view_path(workspace_id, view_id)
        if not isinstance(changes, list) or len(changes) > MAX_COLUMNS:
            raise FmApiError("The filters are not understood.")
        if columns is not None:
            _checked_columns(columns)
        definition = as_dict(self._read("View to filter", base, META))
        if not isinstance(definition.get("columns"), list):
            definition["columns"] = []
        for change in dict_rows(changes):
            column_id, match, filters = _understood_change(change)
            entry = _entry_for(column_id, definition["columns"], lambda: self._fields_meta(workspace_id))
            chosen = _chosen_filters(entry, filters)
            if chosen:
                entry["appliedFilters"] = {"matchRule": match, "filters": chosen}
            else:
                entry.pop("appliedFilters", None)
            log.info("Filters of column %s of view %s: %d chosen", column_id, view_id, len(chosen))
            log_body(log, "filters of", chosen, f"column {column_id} of view {view_id}")
        if columns is not None:
            self._arrange_columns(workspace_id, definition, [str(c) for c in columns])
        self._client.send_json("PUT", base, definition, META)
        return {"columns": parse_columns(definition)}   # what was sent is what the view now holds

    def _arrange_columns(self, workspace_id: str, definition: Dict[str, Any], keys: List[str]) -> None:
        """Make the view's columns exactly ``keys``, in that order: a column not named goes (with its filters), one the view lacks joins from the
        fields the workspace offers. A view that was sorted stays sorted, by its first column if the sorted one went."""
        entries = definition["columns"]
        had_sort = any("sort" in e for e in dict_rows(entries))
        arranged = []
        for key in dict.fromkeys(keys):   # each once
            entry = _entry_for(key, entries, lambda: self._fields_meta(workspace_id))
            entry["displayOrder"] = len(arranged)
            entry.setdefault("visible", True)
            arranged.append(entry)
        if had_sort and not any("sort" in e for e in arranged):
            arranged[0]["sort"] = {"order": 0, "direction": "ASCENDING"}
        definition["columns"] = arranged

    def create_view(self, workspace_id: str, name: str, columns: List[str]) -> Dict[str, Any]:
        """Make a view called ``name`` that shows ``columns`` (field keys, as ``available`` gives them, in the order given) and answer ``{"id"}``.
        The view starts without filters (they are set on it afterwards). Raises ``FmApiError`` when the name or columns are not usable or Fusion
        Manage refuses."""
        name = _checked_name(name)
        columns = _checked_columns(columns)
        offered = {field_key(as_dict(o.get("field"))): o for o in dict_rows(self._fields_meta(workspace_id))}
        body_columns = []
        for key in dict.fromkeys(str(c) for c in columns):   # each once, in the order chosen
            known = offered.get(key)
            if known is None:
                raise FmApiError("The workspace has no such column.")
            body_columns.append({"field": known.get("field"), "group": known.get("group"), "allowMultipleFilters": bool(known.get("allowMultipleFilters")),
                                 "applicableFilters": known.get("applicableFilters") or [], "displayOrder": len(body_columns), "visible": True})
        body_columns[0]["sort"] = {"order": 0, "direction": "ASCENDING"}   # Fusion Manage's own page sends a view sorted by its first column
        body = {"name": name, "columns": body_columns, "isDefault": False,
                "createdDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}
        base = f"{WORKSPACES}/{workspace_id}/tableaus"
        try:
            made = self._client.send_json("POST", base, body, META)
        except FmApiError as exc:
            log.error("The view was refused (%s); the body sent was %d bytes", exc, len(json.dumps(body)))
            log_body(log, "view sent to", json.dumps(body), f"POST {endpoint(base)}")
            raise
        location = next((v for k, v in made.headers.items() if k.lower() == "location"), "")
        view_id = last_segment(location) or id_of(as_dict(made.data))
        log.info("A view made with %d columns: %s", len(body_columns), view_id)
        if not view_id.isdigit():
            raise FmApiError("The view was made, but Fusion Manage did not say which.")
        return {"id": view_id}

    def rename_view(self, workspace_id: str, view_id: str, name: str) -> Dict[str, Any]:
        """Give a view a new name (it is shared, so it changes for everyone) and answer ``{"id", "name"}``. The view is read fresh and written back
        whole with only its name changed. Raises ``FmApiError`` when the name is not usable or the view cannot be read or saved."""
        base = _view_path(workspace_id, view_id)
        name = _checked_name(name)
        definition = as_dict(self._read("View to rename", base, META))
        definition["name"] = name
        try:
            self._client.send_json("PUT", base, definition, META)
        except FmApiError as exc:
            log.error("The view was not renamed (%s); the body sent was %d bytes", exc, len(json.dumps(definition)))
            log_body(log, "view sent to", json.dumps(definition), f"PUT {endpoint(base)}")
            raise
        log.info("View %s of workspace %s renamed", view_id, workspace_id)
        return {"id": view_id, "name": name}

    def delete_view(self, workspace_id: str, view_id: str) -> Dict[str, Any]:
        """Delete a view (it is shared, so it is gone for everyone) and answer ``{"id"}``. Raises ``FmApiError`` when Fusion Manage refuses."""
        self._client.send_json("DELETE", _view_path(workspace_id, view_id))
        log.info("View %s of workspace %s deleted", view_id, workspace_id)
        return {"id": view_id}

    def image(self, workspace_id: str, item_id: str, field: str, number: str) -> Dict[str, Any]:
        """``{"image": data uri}`` of the picture in an image field of an item ("" if it cannot be read). A view's rows give the picture's number,
        and the link is made from it. Raises ``FmApiError`` when the item, field or number is not named properly."""
        if not (item_id.isdigit() and re.fullmatch(r"[A-Z0-9_]+", field) and number.isdigit()):
            raise FmApiError("The picture is not named properly.")
        return {"image": load_image(self._client, f"/api/v2/workspaces/{workspace_id}/items/{item_id}/field-values/{field}/image/{number}")}

    def picture(self, workspace_id: str, link: str) -> Dict[str, Any]:
        """``{"image": data uri}`` of the picture at ``link``, which an item gave for one of its image fields (``/api/v2/workspaces/{ws}/items/{id}/
        field-values/{field}/image/{n}``). Only a picture of an item of this workspace is read. Raises ``FmApiError`` for any other link."""
        found = PICTURE_LINK.fullmatch(link)
        if not found or found.group(1) != workspace_id:
            raise FmApiError("The picture is not named properly.")
        return {"image": load_image(self._client, link)}

    def rows(self, workspace_id: str, view_id: str, page: int, size: int) -> Dict[str, Any]:
        """One page of a view, as ``parse_rows`` gives it plus ``page`` and ``size``. Raises ``FmApiError`` when it cannot be read."""
        base = _view_path(workspace_id, view_id)
        page, size = max(1, whole(page)), min(MAX_SIZE, max(1, whole(size) or DEFAULT_SIZE))
        titles = self._field_titles(workspace_id)
        return {**parse_rows(self._read("Rows", f"{base}?page={page}&size={size}"), titles), "page": page, "size": size}

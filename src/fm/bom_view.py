"""An item's bill of materials as the Bill of Materials tab shows it: a tree of lines with the workspace's BOM columns.

``GET /api/v3/workspaces/{ws}/items/{id}/bom`` answers with ``nodes`` (the items, each with its BOM view fields) and
``edges`` (the lines: parent, child, the line's own fields such as the quantity). Fields name no title there, only
the view definition field they belong to (``.../views/5/viewdef/22/fields/286``), so the titles and the order of the
columns come from ``.../viewdef/22/fields``.
"""

import re
from datetime import date
from typing import Any, Dict, List, Optional, Set

from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, dict_rows, dig, whole
from .bom import ACCEPT, WORKING_BIAS, split_title
from .client import WORKSPACES, FmApiError, FmClient, last_segment
from .item_view import cell_of, no_image, no_page
from .linkable import BOM_VIEW_ID
from .pages import ITEM_LINK, field_id, item_page, link_page, tenant_of

log = get_logger("fm.bom_view")

BOM_DEPTH = 10   # levels read at once: the tree is drawn from one answer
_VIEWDEF = re.compile(r"^(.*/views/[^/]+/viewdef/[^/]+)/fields/[^/]+/?$")
TITLE_KEYS = ("displayName", "name")
# Columns the page draws as an icon, by the field's own id in the workspace
ATTACHMENTS, CHANGE, PIN = "ATTACHMENTS", "WORKING_CHANGE_ORDER", "PIN"
ICON_FIELDS = (ATTACHMENTS, CHANGE, PIN)
IMAGE = "Image"   # the type of a picture field, which the tab does not draw
QUANTITY = "quantity"   # the title of the column whose values are added up in the flat form


def _fields_of(holder: Any) -> Dict[str, Dict[str, Any]]:
    """A node's or edge's fields by view definition field id; the picture fields are left out."""
    found: Dict[str, Dict[str, Any]] = {}
    for field in dict_rows(dig(holder, "fields")):
        fid = field_id(field.get("metaData"))
        kind = dig(field, "type", "title")
        if fid and kind != IMAGE:
            found[fid] = field
    return found


def _viewdef_address(data: Any) -> str:
    """The address of the BOM view definition the answer's fields belong to ("" if no field names it)."""
    for node in dict_rows(dig(data, "nodes")):
        for field in dict_rows(node.get("fields")):
            match = _VIEWDEF.match(str(dig(field, "metaData", "link") or ""))
            if match:
                return match.group(1)
    return ""


def parse_viewdef(data: Any) -> Dict[str, str]:
    """``{view definition field id: title}`` in display order, from the answer of ``.../viewdef/{id}/fields`` (a list)."""
    titles: Dict[str, str] = {}
    for entry in sorted(dict_rows(data), key=lambda e: whole(e.get("displayOrder"))):
        fid = str(entry.get("viewDefFieldId") or "")
        title = next((str(entry[k]) for k in TITLE_KEYS if entry.get(k)), "")
        if fid and title and str(entry.get("visibility") or "ALWAYS").upper() != "NEVER":
            titles[fid] = title
    return titles


def parse_kinds(data: Any) -> Dict[str, str]:
    """``{view definition field id: field id}`` (``ATTACHMENTS``, ``PIN`` ...) from the answer of ``.../viewdef/{id}/fields``."""
    return {str(e["viewDefFieldId"]): str(e.get("fieldId") or "") for e in dict_rows(data) if e.get("viewDefFieldId")}


def _truthy(value: Any) -> bool:
    return bool(value) and str(value).strip().lower() not in ("false", "0", "no", "[]")


def _first_item_link(value: Any) -> str:
    """The API link of the item a field points at (a link, or a list of them), else ""."""
    for option in value if isinstance(value, list) else [value]:
        if isinstance(option, dict) and ITEM_LINK.search(str(option.get("link") or "")):
            return str(option["link"])
    return ""


def _icon_cell(kind: str, field: Dict[str, Any], base_url: str, item: Dict[str, Any], files_page: str) -> Dict[str, Any]:
    """The cell of an icon column: ``attachments`` (a count, linking to the item's attachments), ``change`` (linking to the
    change) or ``pin``. ``value`` is empty when there is nothing to draw."""
    raw = field.get("value")
    log.debug("BOM %s field of %s: value=%r content=%r", kind, item.get("title"), raw, field.get("content"))
    if kind == ATTACHMENTS:
        count = int(raw) if str(raw).strip().isdigit() else 0
        return {"kind": "attachments", "value": str(count) if count else "", "url": files_page if count else ""}
    if kind == PIN:
        return {"kind": "pin", "value": "pinned" if _truthy(raw) else "", "url": ""}
    url = link_page(base_url, tenant_of(item), _first_item_link(raw))
    return {"kind": "change", "value": "pending" if _truthy(raw) else "", "url": url}


def _line(edge: Dict[str, Any], node: Dict[str, Any], base_url: str, hidden: Set[str], kinds: Dict[str, str]) -> Dict[str, Any]:
    item = as_dict(node.get("item"))
    title = str(item.get("title") or "")
    number, name = split_title(title)
    page = item_page(base_url, item)
    files_page = item_page(base_url, item, "attachments", "attachments")
    cells = {}
    for fid, field in {**_fields_of(node), **_fields_of(edge)}.items():   # a field of the line wins over the item's
        if fid in hidden:
            continue
        if kinds.get(fid) in ICON_FIELDS:
            cells[fid] = _icon_cell(kinds[fid], field, base_url, item, files_page)
        else:
            cell = cell_of(field, no_image, no_page)
            cells[fid] = {"kind": cell["kind"], "value": cell["value"]}
    return {"title": title, "number": number, "name": name, "version": str(item.get("version") or ""), "url": page,
            "cells": cells, "children": []}


def _used_fields(lines: List[Dict[str, Any]]) -> Set[str]:
    """The ids of the fields that any of ``lines``, or the lines below them, has a cell for."""
    used: Set[str] = set()
    for line in lines:
        used.update(line["cells"])
        used |= _used_fields(line["children"])
    return used


def _columns(rows: List[Dict[str, Any]], titles: Dict[str, str], kinds: Dict[str, str]) -> List[Dict[str, str]]:
    """The columns that some line has a cell for, in the order of ``titles``. An icon column is headed by its icon, not its name."""
    used = _used_fields(rows)
    return [{"id": fid, "title": title, "icon": kinds[fid] if kinds.get(fid) in ICON_FIELDS else ""} for fid, title in titles.items() if fid in used]


def parse_bom(data: Any, titles: Dict[str, str], base_url: str, root_urn: str, kinds: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """``{"rows": [line], "columns": [{"id", "title"}]}``: one line, the item itself (``root``), with the BOM lines as its ``children`` in BOM order."""
    if not (isinstance(dig(data, "nodes"), list) and isinstance(dig(data, "edges"), list)):
        raise FmApiError("Fusion Manage did not return the Bill of Materials.")
    nodes = {str(dig(n, "item", "urn") or ""): n for n in dict_rows(data["nodes"]) if isinstance(n.get("item"), dict)}
    root = nodes.get(root_urn, {})
    kinds = kinds or {}
    # the descriptor is already the item's title, so its column is not repeated
    hidden = {fid for fid, field in _fields_of(root).items() if field.get("value") == dig(root, "item", "title")}
    below: Dict[str, List[Dict[str, Any]]] = {}
    for edge in dict_rows(data["edges"]):
        below.setdefault(str(edge.get("parent") or ""), []).append(edge)

    def lines(parent: str, seen: Set[str]) -> List[Dict[str, Any]]:
        out = []
        for edge in sorted(below.get(parent, []), key=lambda e: whole(e.get("itemNumber"))):
            child = str(edge.get("child") or "")
            node = nodes.get(child)
            if node is None:
                continue
            line = _line(edge, node, base_url, hidden, kinds)
            if child not in seen:   # a loop in the data would never end
                line["children"] = lines(child, seen | {child})
            out.append(line)
        return out

    top = _line({}, root, base_url, hidden, kinds) if root else None   # the item itself heads the tree, as in the Publish panel
    rows = lines(root_urn, {root_urn})
    if top is not None:
        top.update(root=True, children=rows)
        rows = [top]
    return {"rows": rows, "columns": _columns(rows, titles, kinds)}


def _number(text: str) -> Optional[float]:
    """A cell's text as a number, or None when it is not one."""
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return None


def _quantity_text(value: float) -> str:
    return str(int(value)) if value == int(value) else str(round(value, 4))


def flatten(result: Dict[str, Any]) -> Dict[str, Any]:
    """The flat form of a parsed tree: the item as one line whose children are its leaf components (assemblies and the item itself
    are left out), each once, with the quantity of an item used in several places added up through the assemblies above it."""
    columns = result["columns"]
    qty = next((c["id"] for c in columns if c["title"].strip().lower() == QUANTITY), "")
    leaves: Dict[str, Dict[str, Any]] = {}
    totals: Dict[str, float] = {}
    exact: Dict[str, bool] = {}

    def walk(lines: List[Dict[str, Any]], factor: float) -> None:
        for line in lines:
            own = _number((line["cells"].get(qty) or {}).get("value", "")) if qty else None
            if line.get("root"):
                walk(line["children"], factor)
            elif line["children"]:
                walk(line["children"], factor * (own if own is not None else 1.0))
            else:
                key = line["url"] or line["title"]
                leaves.setdefault(key, {**line, "cells": dict(line["cells"])})
                totals[key] = totals.get(key, 0.0) + factor * (own if own is not None else 1.0)
                exact[key] = exact.get(key, True) and own is not None

    walk(result["rows"], 1.0)
    for key, line in leaves.items():
        if qty and exact[key]:
            value = totals[key]
            line["cells"][qty] = {**line["cells"].get(qty, {"kind": "text"}), "value": _quantity_text(value)}
    top = {**result["rows"][0], "children": list(leaves.values())} if result["rows"] else None
    return {"rows": [top] if top else [], "columns": columns}


def _urn_of(data: Any, item_id: str) -> str:
    """The urn of the item ``item_id`` among the answer's nodes ("" if it is not one of them)."""
    for node in dict_rows(dig(data, "nodes")):
        if str(dig(node, "item", "link") or "").rstrip("/").endswith(f"/items/{item_id}"):
            return str(dig(node, "item", "urn") or "")
    return ""


class BomViewService:
    """Reads an item's bill of materials through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def views(self, workspace_id: str) -> List[Dict[str, Any]]:
        """The BOM views of the workspace, ``[{"id", "name", "default"}]``; empty when they cannot be read (the tab still works with its own view)."""
        try:
            listing = self._client.get_json(f"{WORKSPACES}/{workspace_id}/views/{BOM_VIEW_ID}/")
            found = []
            for entry in dict_rows(dig(listing, "bomViews")):
                link = str(entry.get("link") or "")
                if not link:
                    continue
                definition = as_dict(self._client.get_json(link))
                view_id = str(definition.get("id") or last_segment(link))
                found.append({"id": view_id, "name": str(definition.get("name") or view_id), "default": bool(definition.get("isDefault"))})
            return found
        except FmApiError as exc:
            log.warning("Could not read the BOM views of workspace %s: %s", workspace_id, exc)
            return []

    def read(self, workspace_id: str, item_id: str, view_id: str = "", flat: bool = False) -> Dict[str, Any]:
        """The tree, with the workspace's ``views`` and the id of the one drawn (``view``): ``view_id`` when it is one of them, else the default."""
        views = self.views(workspace_id)
        requested = view_id if view_id and any(v["id"] == view_id for v in views) else ""
        chosen = requested or next((v["id"] for v in views if v["default"]), "")
        result = self._read(workspace_id, item_id, requested)
        if flat:   # Fusion Manage's flat list is the same tree without its assemblies; the plain request for it answers with the item alone
            result = flatten(result)
        return {**result, "views": views, "view": chosen}

    def _read(self, workspace_id: str, item_id: str, view_id: str) -> Dict[str, Any]:
        path = (f"{WORKSPACES}/{workspace_id}/items/{item_id}/bom"
                f"?depth={BOM_DEPTH}&effectiveDate={date.today().isoformat()}&revisionBias={WORKING_BIAS}&rootId={item_id}"
                + (f"&viewDefId={view_id}" if view_id else ""))
        data = self._client.get_json(path, accept=ACCEPT)
        if data is None:   # 204: an item with no lines
            return {"rows": [], "columns": []}
        root_urn = _urn_of(data, item_id)
        address = _viewdef_address(data)
        fields = self._client.get_json(f"{address}/fields") if address else None
        titles = parse_viewdef(fields)
        if not titles and dict_rows(dig(data, "edges")):
            raise FmApiError("Fusion Manage did not name the columns of the Bill of Materials.")
        return parse_bom(data, titles, self._client.base_url, root_urn, parse_kinds(fields))


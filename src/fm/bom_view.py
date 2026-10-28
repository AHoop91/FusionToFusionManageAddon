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
from .bom import WORKING_BIAS
from .client import WORKSPACES, FmApiError, FmClient
from .item_view import cell_of, no_image, no_page
from .linkable import BOM_VIEW_ID
from .pages import ITEM_LINK, field_id, item_page, link_page, tenant_of
from .where_used import split_title

log = get_logger("fm.bom_view")

BOM_DEPTH = 10   # levels read at once: the tree is drawn from one answer
ACCEPT = "application/vnd.autodesk.plm.bom.bulk+json"   # asked for by name: a general Accept is sometimes answered with the tree form (item, fields ...) that has no nodes and edges
_VIEWDEF = re.compile(r"^(.*/views/[^/]+/viewdef/[^/]+)/fields/[^/]+/?$")
TITLE_KEYS = ("displayName", "name")
# Columns the page draws as an icon, by the field's own id in the workspace
ATTACHMENTS, CHANGE, PIN = "ATTACHMENTS", "WORKING_CHANGE_ORDER", "PIN"
ICON_FIELDS = (ATTACHMENTS, CHANGE, PIN)


def _fields_of(holder: Any) -> Dict[str, Dict[str, Any]]:
    """A node's or edge's fields by view definition field id; the picture fields are left out."""
    found: Dict[str, Dict[str, Any]] = {}
    for field in holder.get("fields") if isinstance(holder, dict) and isinstance(holder.get("fields"), list) else []:
        if not isinstance(field, dict):
            continue
        fid = field_id(field.get("metaData"))
        kind = (field.get("type") or {}).get("title") if isinstance(field.get("type"), dict) else ""
        if fid and kind != "Image":
            found[fid] = field
    return found


def _viewdef_address(data: Dict[str, Any]) -> str:
    """The address of the BOM view definition the answer's fields belong to ("" if no field names it)."""
    for node in data.get("nodes") or []:
        for field in node.get("fields") or [] if isinstance(node, dict) else []:
            match = _VIEWDEF.match(str((field.get("metaData") or {}).get("link") or "")) if isinstance(field, dict) else None
            if match:
                return match.group(1)
    return ""


def parse_viewdef(data: Any) -> Dict[str, str]:
    """``{view definition field id: title}`` in display order, from the answer of ``.../viewdef/{id}/fields`` (a list)."""
    entries = [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    titles: Dict[str, str] = {}
    for entry in sorted(entries, key=lambda e: int(e.get("displayOrder") or 0)):
        fid = str(entry.get("viewDefFieldId") or "")
        title = next((str(entry[k]) for k in TITLE_KEYS if entry.get(k)), "")
        if fid and title and str(entry.get("visibility") or "ALWAYS").upper() != "NEVER":
            titles[fid] = title
    return titles


def parse_kinds(data: Any) -> Dict[str, str]:
    """``{view definition field id: field id}`` (``ATTACHMENTS``, ``PIN`` ...) from the answer of ``.../viewdef/{id}/fields``."""
    entries = [e for e in data if isinstance(e, dict) and e.get("viewDefFieldId")] if isinstance(data, list) else []
    return {str(e["viewDefFieldId"]): str(e.get("fieldId") or "") for e in entries}


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
    item = node.get("item") if isinstance(node.get("item"), dict) else {}
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


def parse_bom(data: Any, titles: Dict[str, str], base_url: str, root_urn: str, kinds: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """``{"rows": [line], "columns": [{"id", "title"}]}``: one line, the item itself (``root``), with the BOM lines as its ``children`` in BOM order."""
    if not (isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("edges"), list)):
        raise FmApiError("Fusion Manage did not return the Bill of Materials.")
    nodes = {str((n.get("item") or {}).get("urn") or ""): n for n in data["nodes"] if isinstance(n, dict) and isinstance(n.get("item"), dict)}
    root = nodes.get(root_urn) or {}
    kinds = kinds or {}
    # the descriptor is already the item's title, so its column is not repeated
    hidden = {fid for fid, field in _fields_of(root).items() if field.get("value") == (root.get("item") or {}).get("title")}
    below: Dict[str, List[Dict[str, Any]]] = {}
    for edge in data["edges"]:
        if isinstance(edge, dict):
            below.setdefault(str(edge.get("parent") or ""), []).append(edge)

    def lines(parent: str, seen: Set[str]) -> List[Dict[str, Any]]:
        out = []
        for edge in sorted(below.get(parent, []), key=lambda e: int(e.get("itemNumber") or 0)):
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
    used: List[str] = []

    def collect(items: List[Dict[str, Any]]) -> None:
        for line in items:
            used.extend(fid for fid in line["cells"] if fid not in used)
            collect(line["children"])

    collect(rows)
    order = {fid: i for i, fid in enumerate(titles)}
    columns = [{"id": fid, "title": titles[fid], "icon": kinds.get(fid) if kinds.get(fid) in ICON_FIELDS else ""}   # an icon column is headed by its icon, not its name
               for fid in sorted((f for f in used if f in titles), key=order.get)]
    return {"rows": rows, "columns": columns}


def _number(text: str) -> Optional[float]:
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return None


def flatten(result: Dict[str, Any]) -> Dict[str, Any]:
    """The flat form of a parsed tree: the item as one line whose children are its leaf components (assemblies and the item itself
    are left out), each once, with the quantity of an item used in several places added up through the assemblies above it."""
    columns = result["columns"]
    qty = next((c["id"] for c in columns if c["title"].strip().lower() == "quantity"), "")
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
            line["cells"][qty] = {**line["cells"].get(qty, {"kind": "text"}), "value": str(int(value)) if value == int(value) else str(round(value, 4))}
    top = {**result["rows"][0], "children": list(leaves.values())} if result["rows"] else None
    return {"rows": [top] if top else [], "columns": columns}


class BomViewService:
    """Reads an item's bill of materials through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def views(self, workspace_id: str) -> List[Dict[str, Any]]:
        """The BOM views of the workspace, ``[{"id", "name", "default"}]``; empty when they cannot be read (the tab still works with its own view)."""
        try:
            listing = self._client.get_json(f"{WORKSPACES}/{workspace_id}/views/{BOM_VIEW_ID}/")
            found = []
            for entry in (listing or {}).get("bomViews") or []:
                link = str(entry.get("link") or "") if isinstance(entry, dict) else ""
                if not link:
                    continue
                definition = self._client.get_json(link) or {}
                view_id = str(definition.get("id") or link.rstrip("/").split("/")[-1])
                found.append({"id": view_id, "name": str(definition.get("name") or view_id), "default": bool(definition.get("isDefault"))})
            return found
        except FmApiError as exc:
            log.warning("Could not read the BOM views of workspace %s: %s", workspace_id, exc)
            return []

    def read(self, workspace_id: str, item_id: str, view_id: str = "", flat: bool = False) -> Dict[str, Any]:
        """The tree, with the workspace's ``views`` and the id of the one drawn (``view``): ``view_id`` when it is one of them, else the default."""
        views = self.views(workspace_id)
        chosen = view_id if any(v["id"] == view_id for v in views) else next((v["id"] for v in views if v["default"]), "")
        result = self._read(workspace_id, item_id, chosen if view_id and chosen == view_id else "")
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
        root_urn = next((str((n.get("item") or {}).get("urn") or "") for n in data.get("nodes") or []
                         if isinstance(n, dict) and str((n.get("item") or {}).get("link") or "").rstrip("/").endswith(f"/items/{item_id}")), "")
        address = _viewdef_address(data)
        fields = self._client.get_json(f"{address}/fields") if address else None
        titles = parse_viewdef(fields)
        if not titles and any(isinstance(e, dict) for e in data.get("edges") or []):
            raise FmApiError("Fusion Manage did not name the columns of the Bill of Materials.")
        return parse_bom(data, titles, self._client.base_url, root_urn, parse_kinds(fields))


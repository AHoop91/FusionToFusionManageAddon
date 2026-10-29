"""An item as Fusion Manage's Item tab shows it: a header and sections of fields and matrices.

``GET /api/v3/workspaces/{ws}/items/{id}`` gives each section's fields with their values, flat. How a
workspace groups fields into matrices (grids with row and column names) is only in the workspace's own
section layouts, so the two are combined: values from the item, matrices from the layout. A field
that sits in a matrix is shown there and not again as a plain field.

A value is plain text, an image (fetched here, since it needs the sign-in, and handed over as a data
uri) or HTML (what a formula field writes; the page sanitises it before showing it).
"""

import base64
import html
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..auth.errors import AuthError
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list, dict_rows, dig, rows_in
from .client import WORKSPACES, FmApiError, FmClient, last_segment
from .items import display_text
from .pages import field_id, item_page, link_page, tenant_of
from .sections import SectionService
from .tabs import TabService
from .ttl_cache import TtlCache

log = get_logger("fm.item_view")

HIDDEN = ("NEVER", "HIDDEN", "NONE")   # visibility values of a field that is not shown on the item
VISIBLE_ALWAYS = ("ALWAYS", "VISIBLE")
HEADER_FIELDS = ("TYPE",)   # read for the line under the title, shown or not
MAX_IMAGE_BYTES = 2_000_000
LOG_CHARS = 3000   # of an answer that could not be laid out, kept in the log
IMAGE, CHECK_BOX = "Image", "Check Box"   # the types of field that are drawn or worded differently
COLUMN_KEYS = ("columns", "columnNames", "columnTitles")   # where a matrix layout may name its columns and rows, in the order tried
ROW_KEYS = ("rows", "rowNames", "rowTitles")
_TAG = re.compile(r"<[a-zA-Z][^>]*>")

ImageLoader = Callable[[str], str]
PageLoader = Callable[[str], str]   # an item's API link -> its page in Fusion Manage ("" for a link that is not an item)


def no_image(_link: str) -> str:
    """An image loader for a view that does not draw pictures."""
    return ""


def no_page(_link: str) -> str:
    """A page finder for a view that does not link to items."""
    return ""


def _item_links(raw: Any, pages: PageLoader) -> List[Dict[str, str]]:
    """``[{"title", "url"}]`` when ``raw`` is a link to an item, or a list of them, each of which has a page; else ``[]``."""
    options = raw if isinstance(raw, list) else [raw]   # a picklist that links to items: each is a link to open
    links = [{"title": display_text(o) or last_segment(o.get("link")), "url": pages(str(o.get("link") or ""))} for o in options if isinstance(o, dict)]
    return links if links and len(links) == len(options) and all(link["url"] for link in links) else []


def _text_of(node: Dict[str, Any], kind: str) -> str:
    """The text a plain field shows: a check box as Yes or No, a value with its unit of measure."""
    text = display_text(node.get("value"))
    if kind == CHECK_BOX and text in ("true", "false"):
        text = "Yes" if text == "true" else "No"
    return f"{text} {node['uom']}" if text and node.get("uom") else text


def cell_of(node: Dict[str, Any], images: ImageLoader, pages: PageLoader) -> Dict[str, Any]:
    """``{"id", "title", "kind", "value"}`` of an item's field; kind is ``text``, ``html``, ``image`` or ``links`` (a list of ``{"title", "url"}``)."""
    raw = node.get("value")
    kind = dig(node, "type", "title") or ""
    cell = {"id": field_id(node), "title": str(node.get("title") or node.get("name") or field_id(node)), "kind": "text", "value": ""}
    if kind == IMAGE:
        link = str(dig(node, "value", "link") or "")
        return {**cell, "kind": "image", "value": images(link) if link else ""}
    links = _item_links(raw, pages)
    if links:
        return {**cell, "kind": "links", "value": links}
    if isinstance(raw, str):
        decoded = html.unescape(raw)   # a formula field's markup arrives escaped
        if _TAG.search(decoded):
            return {**cell, "kind": "html", "value": decoded}
    return {**cell, "value": _text_of(node, kind)}


def not_shown(node: Any, hidden: Set[str]) -> bool:
    """Whether a field (as the item, the layout or the workspace's field list gives it) is not to be shown."""
    if not isinstance(node, dict):
        return False
    visibility = str(node.get("visibility") or "").upper()
    if visibility not in VISIBLE_ALWAYS and (visibility in HIDDEN or ("CREATE" in visibility and "ONLY" in visibility)):   # "CREATE_ONLY" and the like
        return True
    return node.get("visible") is False or node.get("hidden") is True or field_id(node) in hidden


def _names(layout: Dict[str, Any], keys: Tuple[str, ...]) -> List[str]:
    """The titles a matrix layout gives its columns or rows: those under the first of ``keys`` that holds any (empty if none does)."""
    for key in keys:
        found = as_list(layout.get(key))
        if found:
            return [str(f.get("title") or f.get("name") or "") if isinstance(f, dict) else str(f) for f in found]
    return []


def _matrix(layout: Dict[str, Any], cells: Dict[str, Dict[str, str]], hidden: Set[str]) -> Dict[str, Any]:
    """A matrix of the workspace layout filled from the item: ``{"columns", "labels", "rows": [[cell]]}``.

    A row or column whose fields are all hidden is left out; a hidden field inside a shown row is blank.
    """
    grid = [row for row in as_list(layout.get("fields")) if isinstance(row, list)]
    if not grid:
        return {}
    width = max(len(r) for r in grid)
    gone = [[not_shown(ref, hidden) or bool(field_id(ref) and field_id(ref) not in cells) for ref in row] + [False] * (width - len(row))
            for row in grid]
    keep_cols = [c for c in range(width) if not all(g[c] for g in gone)]
    keep_rows = [r for r, g in enumerate(gone) if not all(g[c] for c in keep_cols)] if keep_cols else []
    if not keep_rows:
        return {}
    empty = {"kind": "text", "value": ""}
    rows = [[cells.get(field_id(grid[r][c]), empty) if c < len(grid[r]) and not gone[r][c] else empty for c in keep_cols]
            for r in keep_rows]
    all_columns = _names(layout, COLUMN_KEYS)
    if len(all_columns) == width:
        columns = [all_columns[c] for c in keep_cols]
    else:   # not named by the layout: the first row's field titles
        columns = [rows[0][i].get("title", "") for i in range(len(keep_cols))]
    all_labels = _names(layout, ROW_KEYS)
    labels = [all_labels[r] for r in keep_rows] if len(all_labels) == len(grid) else [""] * len(rows)
    return {"columns": columns, "labels": labels, "rows": [[{"kind": c["kind"], "value": c["value"]} for c in r] for r in rows]}


def _header(item: Dict[str, Any], fields: Dict[str, Dict[str, str]]) -> List[str]:
    """The line under the title: where the item is in its life cycle, and its type (the number is already in the title)."""
    version = "Pending" if item.get("versionId") == "w" else str(item.get("version") or "")
    lifecycle = display_text(item.get("lifecycle"))
    kind = fields.get("TYPE", {}).get("value", "")
    return [t for t in (version, lifecycle, kind) if t]


def _cells(nodes: List[Dict[str, Any]], images: ImageLoader, pages: PageLoader) -> Dict[str, Dict[str, Any]]:
    """The cells of the fields ``nodes`` by field id, in order; a field with no id has none."""
    cells = (cell_of(node, images, pages) for node in nodes)
    return {cell["id"]: cell for cell in cells if cell["id"]}


def _section(node: Dict[str, Any], cells: Dict[str, Dict[str, Any]], layout: Dict[str, Any], hidden: Set[str]) -> Optional[Dict[str, Any]]:
    """A section of the view from its ``cells`` and the workspace's ``layout`` of it; None when nothing in it is shown."""
    grids = dict_rows(layout.get("matrices"))
    matrices = [m for m in (_matrix(grid, cells, hidden) for grid in grids) if m]
    in_matrix = {field_id(ref) for grid in grids for row in as_list(grid.get("fields")) for ref in as_list(row)}   # shown there, not again
    fields = [cell for fid, cell in cells.items() if fid not in in_matrix]
    if not fields and not matrices:
        return None
    return {"title": str(node.get("title") or ""), "fields": fields, "matrices": matrices}


def build_view(item: Any, layouts: Dict[str, Dict[str, Any]], images: ImageLoader, base_url: str = "",
               hidden: Optional[Set[str]] = None) -> Dict[str, Any]:
    """The header and sections of an item answer; ``layouts`` maps a section id to the workspace's layout of it.

    ``hidden`` holds the ids of fields the workspace does not show; a field that says so itself is left out too.
    """
    item = as_dict(item)
    hidden = hidden or set()
    tenant = tenant_of(item)

    def pages(link: str) -> str:
        return link_page(base_url, tenant, link)

    sections: List[Dict[str, Any]] = []
    header_cells: Dict[str, Dict[str, Any]] = {}
    for node in dict_rows(item.get("sections")):
        found = dict_rows(node.get("fields"))
        header_cells.update(_cells([f for f in found if field_id(f) in HEADER_FIELDS], images, pages))
        cells = _cells([f for f in found if not not_shown(f, hidden)], images, pages)
        layout = as_dict(layouts.get(last_segment(node.get("link") or node.get("__self__"))))
        section = _section(node, cells, layout, hidden)
        if section:
            sections.append(section)
    return {"title": str(item.get("title") or ""), "workspace": str(dig(item, "workspace", "title") or ""),
            "header": _header(item, header_cells), "url": item_page(base_url, item), "sections": sections}


class ItemViewService:
    """Reads an item through an ``FmClient`` and lays it out for display."""

    _hidden_cache = TtlCache()   # (tenant, workspace id) -> hidden field ids; a workspace's field list rarely changes

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def prepare(self, workspace_id: str) -> None:
        """Read what a workspace shares between its items (section layouts, hidden fields, tab names) all at once, so a ``read`` finds it
        cached. It needs no item, so it can run while the item is still being found. A failure is left for ``read`` to report."""
        steps = (lambda: SectionService(self._client).layouts(workspace_id), lambda: self._hidden_fields(workspace_id),
                 lambda: TabService(self._client).labels(workspace_id))
        with ThreadPoolExecutor(max_workers=len(steps)) as pool:
            for pending in [pool.submit(step) for step in steps]:
                try:
                    pending.result()
                except (FmApiError, AuthError) as exc:
                    log.debug("Preparing workspace %s: %s", workspace_id, exc)

    def read(self, workspace_id: str, item_id: str, held: Set[str]) -> Dict[str, Any]:
        """The item laid out for display; ``held`` is the user's permissions in the workspace (they decide which tabs can be opened)."""
        with ThreadPoolExecutor(max_workers=2) as pool:
            # the other tabs are read when they are opened; only their names and counts come with the item
            tabs = pool.submit(TabService(self._client).read, workspace_id, item_id, held)   # asked while the item is read
            layouts = pool.submit(self._layouts, workspace_id)
            data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/items/{item_id}")
            if not isinstance(data, dict):
                raise FmApiError(f"Fusion Manage gave no item {item_id} in workspace {workspace_id}.")
            view = build_view(data, layouts.result(), self._image, self._client.base_url, self._hidden_fields(workspace_id))
            if not view["sections"]:   # the answer was not laid out as expected: keep the start of it in the log
                log.error("No sections could be built for item %s: %s", item_id, str(data)[:LOG_CHARS])
            view["tabs"] = tabs.result()
        view["item_id"], view["workspace_id"], view["item_urn"] = item_id, workspace_id, str(data.get("urn") or "")
        return view

    def _layouts(self, workspace_id: str) -> Dict[str, Dict[str, Any]]:
        try:
            layouts = SectionService(self._client).layouts(workspace_id)
        except FmApiError as exc:   # the fields still show, without their matrices
            log.warning("Could not read the section layout of workspace %s: %s", workspace_id, exc)
            return {}
        for layout in list(layouts.values())[:3]:
            log.debug("Section %s layout keys: %s; matrices: %s", last_segment(str(layout.get("__self__") or layout.get("link") or "")),
                     sorted(layout), [sorted(m) for m in dict_rows(layout.get("matrices"))[:1]])
        return layouts

    def _hidden_fields(self, workspace_id: str) -> Set[str]:
        """Ids of the workspace's fields that are not to be shown on an item (empty if the field list cannot be read)."""
        key = (self._client.tenant, workspace_id)
        cached = self._hidden_cache.get(key)
        if cached is not None:
            return cached
        try:
            data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/fields")
        except FmApiError as exc:   # every field shows
            log.warning("Could not read the fields of workspace %s: %s", workspace_id, exc)
            return set()
        rows = rows_in(data, "fields")
        hidden = {last_segment(r.get("__self__")) for r in rows if not_shown(r, set())}
        log.debug("Workspace %s: %d field(s), %d hidden; visibility values %s", workspace_id, len(rows), len(hidden),
                 sorted({str(r.get("visibility")) for r in rows}))
        return self._hidden_cache.put(key, hidden)

    def _image(self, link: str) -> str:
        """An image field's picture as a data uri ("" when it cannot be read or is too big)."""
        if not link.startswith("/"):
            return ""
        try:
            body, kind = self._client.get_bytes(link)
        except (FmApiError, OSError) as exc:
            log.warning("Could not read the image %s: %s", link, exc)
            return ""
        if len(body) > MAX_IMAGE_BYTES or not kind.lower().startswith("image/"):
            return ""
        return f"data:{kind.split(';')[0]};base64,{base64.b64encode(body).decode('ascii')}"

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
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from ..auth.errors import AuthError
from ..core.logging_setup import endpoint, get_logger, log_body
from ..core.shapes import as_dict, as_list, dict_rows, dig, rows_in
from .client import WORKSPACES, FmApiError, FmClient, last_segment
from .items import ItemService, display_text
from .pages import field_id, item_page, link_page, tenant_of
from .sections import SectionService
from .tabs import TabService
from .ttl_cache import TtlCache

log = get_logger("fm.item_view")

HIDDEN = ("NEVER", "HIDDEN", "NONE")   # visibility values of a field that is not shown on the item
VISIBLE_ALWAYS = ("ALWAYS", "VISIBLE")
HEADER_FIELDS = ("TYPE",)   # read for the line under the title, shown or not
MAX_IMAGE_BYTES = 2_000_000
MAX_PICTURES_AT_ONCE = 6   # pictures of an item downloaded together
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


def load_image(client: FmClient, link: str) -> str:
    """An image field's picture as a data uri ("" when it cannot be read or is too big)."""
    if not link.startswith("/"):
        return ""
    try:
        body, kind = client.get_bytes(link)
    except (FmApiError, OSError) as exc:
        log.warning("Could not read the image %s: %s", endpoint(link), exc)
        return ""
    if len(body) > MAX_IMAGE_BYTES or not kind.lower().startswith("image/"):
        return ""
    return f"data:{kind.split(';')[0]};base64,{base64.b64encode(body).decode('ascii')}"


def _image_links(node: Any) -> Iterator[str]:
    """The link of the picture of every image field in ``node`` (an item's answer) that holds one."""
    if isinstance(node, dict):
        if dig(node, "type", "title") == IMAGE:
            link = str(dig(node, "value", "link") or "")
            if link:
                yield link
        for value in node.values():
            yield from _image_links(value)
    elif isinstance(node, list):
        for value in node:
            yield from _image_links(value)


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
        return {**cell, "kind": "image", "link": link, "value": images(link) if link else ""}   # a page that was given no picture asks for ``link`` itself
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


def layout_names(layout: Dict[str, Any], keys: Tuple[str, ...]) -> List[str]:
    """The titles a matrix layout gives its columns or rows: those under the first of ``keys`` that holds any (empty if none does)."""
    for key in keys:
        found = as_list(layout.get(key))
        if found:
            return [str(f.get("title") or f.get("name") or "") if isinstance(f, dict) else str(f) for f in found]
    return []


def _hidden_grid(grid: List[List[Any]], cells: Dict[str, Dict[str, str]], hidden: Set[str]) -> List[List[bool]]:
    """For each field reference of the layout's grid (rows padded to the widest): whether it is not shown or has no value in the item."""
    width = max(len(r) for r in grid)
    return [[not_shown(ref, hidden) or bool(field_id(ref) and field_id(ref) not in cells) for ref in row] + [False] * (width - len(row))
            for row in grid]


def _kept_columns_and_rows(gone: List[List[bool]], width: int) -> Tuple[List[int], List[int]]:
    """The indexes of the columns, then the rows, that have any field shown (no rows when no column is kept)."""
    keep_cols = [c for c in range(width) if not all(g[c] for g in gone)]
    if not keep_cols:
        return keep_cols, []
    return keep_cols, [r for r, g in enumerate(gone) if not all(g[c] for c in keep_cols)]


def _row_labels(layout: Dict[str, Any], height: int, keep_rows: List[int]) -> List[str]:
    """The titles of the kept rows: the layout's own when it names every row, else blank."""
    all_labels = layout_names(layout, ROW_KEYS)
    return [all_labels[r] for r in keep_rows] if len(all_labels) == height else [""] * len(keep_rows)


def _matrix_cell(row: List[Any], column: int, is_gone: bool, cells: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """The cell at ``column`` of a layout row: blank when it is hidden, past the row's end or has no value in the item."""
    if column < len(row) and not is_gone:
        return cells.get(field_id(row[column]), {"kind": "text", "value": ""})
    return {"kind": "text", "value": ""}


def _column_names(layout: Dict[str, Any], rows: List[List[Dict[str, Any]]], width: int, keep_cols: List[int]) -> List[str]:
    """The titles of the kept columns: the layout's own when it names every column, else the first row's field titles."""
    all_columns = layout_names(layout, COLUMN_KEYS)
    if len(all_columns) == width:
        return [all_columns[c] for c in keep_cols]
    return [rows[0][i].get("title", "") for i in range(len(keep_cols))]


def _matrix(layout: Dict[str, Any], cells: Dict[str, Dict[str, str]], hidden: Set[str]) -> Dict[str, Any]:
    """A matrix of the workspace layout filled from the item: ``{"columns", "labels", "rows": [[cell]]}``.

    A row or column whose fields are all hidden is left out; a hidden field inside a shown row is blank.
    """
    grid = [row for row in as_list(layout.get("fields")) if isinstance(row, list)]
    if not grid:
        return {}
    width = max(len(r) for r in grid)
    gone = _hidden_grid(grid, cells, hidden)
    keep_cols, keep_rows = _kept_columns_and_rows(gone, width)
    if not keep_rows:
        return {}
    rows = [[_matrix_cell(grid[r], c, gone[r][c], cells) for c in keep_cols] for r in keep_rows]
    shown = [[{key: c[key] for key in ("kind", "value", "link") if key in c} for c in r] for r in rows]   # a picture's link goes too
    return {"columns": _column_names(layout, rows, width, keep_cols), "labels": _row_labels(layout, len(grid), keep_rows), "rows": shown}


def revision_and_state(item: Dict[str, Any]) -> Tuple[str, str]:
    """``(revision, life cycle state)`` of an item as Fusion Manage gives it ("Pending" for a working version, "" for what it does not give)."""
    version = "Pending" if item.get("versionId") == "w" else str(item.get("version") or "")
    return version, display_text(item.get("lifecycle"))


def _header(item: Dict[str, Any], fields: Dict[str, Dict[str, str]]) -> List[str]:
    """The line under the title: where the item is in its life cycle, and its type (the number is already in the title)."""
    version, lifecycle = revision_and_state(item)
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
    return {"title": str(node.get("title") or ""), "collapsed": layout.get("collapsed") is True, "fields": fields, "matrices": matrices}


# 5 parameters: the answer, the layouts, how to load pictures, the address to link with, and the hidden fields are five separate things the
# callers (ItemViewService and the tests) already hold; a bundle would only be built to be taken apart.
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
            "header": _header(item, header_cells), "state": display_text(item.get("currentState")), "url": item_page(base_url, item),
            "sections": sections}


class ItemViewService:
    """Reads an item through an ``FmClient`` and lays it out for display."""

    _hidden_cache = TtlCache()   # (tenant, workspace id) -> hidden field ids; a workspace's field list rarely changes

    def __init__(self, client: FmClient) -> None:
        self._client = client

    @classmethod
    def forget(cls) -> None:
        """Drop the layout kept of every workspace (sections, hidden fields, tab names): the next read asks Fusion Manage again."""
        SectionService.forget()
        TabService.forget()
        cls._hidden_cache.clear()

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

    def layout(self, workspace_id: str, item_id: str, pictures: bool = True) -> Dict[str, Any]:
        """The item laid out for display (title, header, state, url, ``sections``, ``item_id``, ``workspace_id``, ``item_urn``), with no ``tabs`` and so no
        permissions read. ``pictures`` False leaves the image fields empty, each with its ``link``, so the page can draw the item at once and ask for the
        pictures afterwards (they are the slowest part of a read)."""
        with ThreadPoolExecutor(max_workers=2) as pool:   # the workspace's layout is read while the item is
            layouts = pool.submit(self._layouts, workspace_id)
            hidden = pool.submit(self._hidden_fields, workspace_id)
            data = ItemService(self._client).item(workspace_id, item_id)
            loader = self._pictures(data) if pictures else no_image
            view = build_view(data, layouts.result(), loader, self._client.base_url, hidden.result())
        if not view["sections"]:   # the answer was not laid out as expected: keep the start of it in the log
            log.error("No sections could be built for item %s: the answer was a %s", item_id, type(data).__name__)
            log_body(log, "item", data, str(item_id))
        view["item_id"], view["workspace_id"], view["item_urn"] = item_id, workspace_id, str(data.get("urn") or "")
        return view

    # 5 parameters: the item, the user's permissions, and two flags that pass straight on to ``layout`` and ``TabService.read``.
    def read(self, workspace_id: str, item_id: str, held: Set[str], with_grid: bool = False, pictures: bool = True) -> Dict[str, Any]:
        """``layout`` with the item's ``tabs`` (see ``TabService.read``); ``held`` is the user's permissions in the workspace (they decide which tabs can
        be opened) and ``with_grid`` adds the Grid tab."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            # the other tabs are read when they are opened; only their names and counts come with the item
            tabs = pool.submit(TabService(self._client).read, workspace_id, item_id, held, with_grid)   # asked while the item is read
            view = self.layout(workspace_id, item_id, pictures)
            view["tabs"] = tabs.result()
        return view

    def _layouts(self, workspace_id: str) -> Dict[str, Dict[str, Any]]:
        try:
            layouts = SectionService(self._client).layouts(workspace_id)
        except FmApiError as exc:   # the fields still show, without their matrices
            log.warning("Could not read the section layout of workspace %s: %s", workspace_id, exc)
            return {}
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

    def _pictures(self, item: Any) -> ImageLoader:
        """The loader of the item's pictures, all downloaded at once: each is a read of its own, and an item can hold several."""
        links = list(dict.fromkeys(_image_links(item)))
        if not links:
            return no_image
        with ThreadPoolExecutor(max_workers=min(len(links), MAX_PICTURES_AT_ONCE)) as pool:
            loaded = dict(zip(links, pool.map(lambda link: load_image(self._client, link), links)))
        return lambda link: loaded.get(link, "")


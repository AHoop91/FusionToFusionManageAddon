"""Creating and editing a product in the Portfolio Management workspace.

A product is an item of the Portfolio Management workspace, created with the same item request as any item, from the values the form of
the workspace collected (see ``fm.workspace_form``). What the workspace needs is for Fusion Manage to say: it refuses a create that lacks
something, and what it says is shown as it is.

Assigning a component to a product sets its Primary Component field, or, when the product has one already and the person says so, adds the
component to the Variants grid as a row.

Editing reads the item, sends only the values that differ from what it holds (the update the publish makes: ``PATCH``), and sends nothing
when none do. A value left blank is never sent, so clearing a field is not something an edit can do.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.i18n import t
from ..core.shapes import as_dict, dict_rows, rows_in
from ..core.logging_setup import get_logger
from ..fm.client import WORKSPACES, FmApiError, FmClient, SendResult, last_segment
from ..fm.bom import split_title
from ..fm.components import Candidate, ComponentService, is_working, number_matches
from ..fm.items import ItemService, display_text
from ..fm.permissions import REFUSED
from ..fm.pages import link_page, page_url
from ..fm.tableaus import PICTURE_LINK
from ..fm.v1_search import GRIDVIEW, Field, Sort, V1Row, V1SearchService
from ..fm.v3_search import number_key
from ..fm.refusal import read_refusal
from ..fm.sections import SectionService
from ..fm.workspace import GRID_VIEW, WorkspaceService
from ..sync.property_compare import FOUND, MISMATCH, NEW
from .item_requests import field_value, holds, item_request
from .sender import created_id


log = get_logger("publish.products")

BAD_REQUEST, UNPROCESSABLE = 400, 422   # a payload Fusion Manage cannot read; what a refusal of it is reported as (the panel takes a plain 400 for a bad search)
REPLACE, VARIANT, REPLACE_MOVE = "replace", "variant", "replace_move"   # what to do with a Primary Component that is there already (the last also keeps it as a variant)
ASSIGNED, SAME, EXISTS, ADDED = "assigned", "same", "exists", "variant"   # how an assign ended
REVISION, OTHER, UPDATED = "revision", "other", "updated"   # a component held already: the same number in another revision, or another component; how a row ended
VARIANT_UPDATE = "variant_update"   # change the revision of a row of the Variants grid that holds the component already


def _has_value(current: Any) -> bool:
    """Whether a link field holds something."""
    return bool(display_text(current).strip()) or (isinstance(current, dict) and bool(current.get("link")))


def _links(items: List[Any]) -> List[str]:
    """The links of a list of link values, in order."""
    return sorted(str(item.get("link")) for item in items if isinstance(item, dict))


def _same(current: Any, value: Any) -> bool:
    """Whether the item holds ``value`` already (a list of links, for a field of several items, in any order)."""
    if isinstance(value, list):
        return isinstance(current, list) and _links(current) == _links(value)
    return holds(current, value)


def _item_id(candidate: Candidate) -> int:
    """The id of the item an option stands for (the end of its link; an option has the id of its item): later revisions have the larger ids."""
    last = last_segment(candidate.link)
    return int(last) if last.isdigit() else -1


def _relation(link: str, title: str, number: str, chosen: Candidate) -> str:
    """How a component the product holds (its ``link`` and ``title``) stands to the one being assigned: ``same`` (the revision chosen), ``revision``
    (the same item number, another revision) or ``other``. An option has the id of its item, so the revisions are told apart by that id."""
    if link and last_segment(link) == last_segment(chosen.link):
        return SAME
    return REVISION if number_key(title) == number.strip().lower() else OTHER


def _latest_revision(hits: List[Candidate]) -> Candidate:
    """The option to assign: the latest released revision (the one with the largest id that is not the working version), and the working version
    only when the component has no released revision. The Data Model cannot say: the item it links a design to is the working version's whether
    it is asked for the RELEASED composition or the WORKING one."""
    released = [c for c in hits if not is_working(c.version)]
    return max(released or hits, key=_item_id)


def _link_of(value: Any) -> str:
    """The link a field value holds ("" when it is not a link)."""
    link = as_dict(value).get("link")
    return link if isinstance(link, str) else ""


def _picture_link(values: Dict[str, Any]) -> str:
    """The link of the first picture among the field values of an item ("" when it holds none)."""
    return next((link for link in map(_link_of, values.values()) if PICTURE_LINK.fullmatch(link)), "")


class NotAllowed(Exception):
    """Fusion Manage does not let the user in: their app's Client ID has no user mapped to it, or they may not read the workspace."""


class ProductService:
    """Creates products through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def create(self, workspace_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Create a product with ``values`` (``{field id: value}``; a picklist's value is the link of its option); answers ``{"id", "link"}``.
        A value left blank is not sent. Raises ``FmApiError`` with Fusion Manage's reason when it is refused."""
        rows = [{"fm_field": field_id, "value": value, "status": NEW} for field_id, value in values.items()]
        item_id = created_id(self._write(workspace_id, {"state": NEW}, rows))
        return {"id": item_id, "link": f"{WORKSPACES}/{workspace_id}/items/{item_id}" if item_id else ""}

    def read(self, workspace_id: str, item_id: str) -> Dict[str, Any]:
        """The values of a product as Fusion Manage holds them (``{field id: value}``; a picklist or a link is ``{"link", "title"}``)."""
        return ItemService(self._client).read(workspace_id, item_id)

    def update(self, workspace_id: str, item_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Change the product to ``values`` (as ``create`` takes them): only what differs from what it holds is sent. Answers ``{"id", "link",
        "unchanged"}``. Raises ``FmApiError`` with Fusion Manage's reason when it is refused."""
        current = self.read(workspace_id, item_id)
        rows = [{"fm_field": field_id, "value": value, "status": MISMATCH} for field_id, value in values.items()
                if not _same(current.get(field_id), value)]
        link = f"{WORKSPACES}/{workspace_id}/items/{item_id}"
        if not rows:
            return {"id": item_id, "link": link, "unchanged": True}
        self._write(workspace_id, {"state": FOUND, "item_id": item_id}, rows)
        return {"id": item_id, "link": link, "unchanged": False}

    def _write(self, workspace_id: str, fm: Dict[str, Any], rows: List[Dict[str, Any]]) -> SendResult:
        """Send the item request for ``rows`` (a create when ``fm`` has the state NEW, an update for FOUND). Raises ``FmApiError``: with what
        Fusion Manage refused, shown beside the fields it names, or with the reason there is nothing to send."""
        sections = SectionService(self._client).field_sections(workspace_id)
        request, reason = item_request(workspace_id, fm, rows, [], sections)
        if request is None:
            raise FmApiError(reason or t("app.product_no_values"))
        try:
            return self._client.send_json(request["method"], request["url"], request["body"])
        except FmApiError as exc:
            raise read_refusal(exc, set(sections), t("app.product_refused")) from exc

    def _options_of(self, workspace_id: str, field_id: str, number: str, grid: bool = False) -> Tuple[List[Candidate], Candidate]:
        """The options of the component with ``number`` in the picklist that the field ``field_id`` (of the workspace, or of its Grid tab when
        ``grid``) takes its components from, and the one to assign among them. Raises ``FmApiError`` when the field cannot be read, no longer
        links to a picklist, or the component is not found."""
        service = WorkspaceService(self._client)
        base = f"{WORKSPACES}/{workspace_id}"
        fields, error = service.grid_fields(base) if grid else service.fields(base)
        if error:
            raise FmApiError(error)
        lookup = next((f["link_lookup"] for f in fields if f["id"] == field_id), "")
        if not lookup:
            raise FmApiError(t("app.product_field_not_linked", field=field_id, workspace=workspace_id))
        hits = ComponentService(self._client).matching(lookup, number)
        return hits, _latest_revision(hits)

    def assign(self, workspace_id: str, item_id: str, number: str, field_id: str, link_column: str, mode: str = "",
               row_values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make the component with ``number`` the product's Primary Component (``field_id``), a PATCH of that field when it is empty.

        A component has an option for each of its revisions: the latest released revision is the one assigned, and the working version when there
        is no released revision.

        When the product holds a different Primary Component already, nothing is changed and ``{"status": "exists", "current"}`` says so, so the
        person can choose: ``mode`` ``replace`` changes it, ``replace_move`` changes it and adds the one that was there as a row of the Variants grid
        (its ``link_column``), ``variant`` adds the component as a row of the Variants grid instead. ``row_values`` (``{column id: value}``) are the
        other columns of a row added to the grid: the same for each row added.
        Answers ``{"status", "number", "current", "component"}``; ``same`` means the component is the Primary Component already.
        Raises ``FmApiError`` with the reason."""
        hits, chosen = self._options_of(workspace_id, field_id, number)
        log.info("Assign %s to product %s: options %s -> %s %s", number, item_id, [f"{last_segment(c.link)} {c.version}" for c in hits],
                 last_segment(chosen.link), chosen.version)
        product, values = ItemService(self._client).read_named(workspace_id, item_id)
        current = values.get(field_id)
        named = display_text(current).strip() if _has_value(current) else ""
        answer = {"number": number, "current": named, "component": chosen.link, "product": product}
        held = _has_value(current)
        if held and holds(current, {"link": chosen.link}):
            return {**answer, "status": SAME}
        if held and mode not in (REPLACE, VARIANT, REPLACE_MOVE):
            return {**answer, "status": EXISTS}
        if mode == VARIANT:
            self._add_variant(workspace_id, item_id, number, link_column, chosen, row_values or {})
            return {**answer, "status": ADDED}
        if mode == REPLACE_MOVE and held:   # the one that is replaced is kept, as a variant (first: a refusal leaves the product as it was)
            old = _link_of(current)
            if not old:
                raise FmApiError(t("app.product_move_no_link", current=named))
            self._post_variant(workspace_id, item_id, link_column, old, row_values or {})
        self.update(workspace_id, item_id, {field_id: {"link": chosen.link}})
        return {**answer, "status": ASSIGNED}

    def inspect(self, workspace_id: str, item_id: str, number: str, field_id: str, link_column: str) -> Dict[str, Any]:
        """What the product holds of components, and how the component with ``number`` (its revision to assign: see ``assign``) stands to it:

        ``{"product", "number", "component", "revision", "primary", "primary_state", "columns", "rows"}``. ``primary`` is ``{"link", "title",
        "revision"}`` or None; each row of the Variants grid is ``{"id", "link", "title", "revision", "state", "cells"}`` (``cells`` is the text of
        each column by its id) and ``columns`` is ``[{"id", "title"}]`` for the grid. A ``state`` is ``same``, ``revision`` or ``other`` (see
        ``_relation``); ``revision`` is the label of the revision of a component of this number ("" otherwise). Raises ``FmApiError`` with the reason."""
        hits, chosen = self._options_of(workspace_id, field_id, number)
        product, values = ItemService(self._client).read_named(workspace_id, item_id)
        current = values.get(field_id)
        revisions = {last_segment(c.link): c.version for c in hits}

        def stand(link: str, title: str) -> Dict[str, Any]:
            return {"link": link, "title": title, "revision": revisions.get(last_segment(link), ""), "state": _relation(link, title, number, chosen)}

        primary = None
        if _has_value(current):
            primary = stand(_link_of(current), display_text(current).strip())
        columns, rows = self._grid(workspace_id, item_id, link_column, stand)
        return {"product": product, "number": number, "component": chosen.link, "revision": chosen.version, "title": chosen.title,
                "primary": primary, "primary_state": primary["state"] if primary else "", "link_column": link_column, "columns": columns, "rows": rows}

    def contents(self, workspace_id: str, item_id: str, field_id: str, link_column: str) -> Dict[str, Any]:
        """What the product holds of components, for browsing, with no design involved: ``{"product", "primary", "link_column", "columns", "rows"}``.
        ``primary`` is ``{"link", "title"}`` or None when it has none; ``columns`` and each of the ``rows`` of the Variants grid are as in ``inspect``,
        a row's ``link``, ``title`` and ``url`` (its page in Fusion Manage) being the component it names ("" when it names none, or when
        ``link_column`` is "": the Variants column is not set up). Raises ``FmApiError`` with the reason."""
        client = self._client
        with ThreadPoolExecutor(max_workers=1) as pool:
            named = pool.submit(ItemService(client).read_named, workspace_id, item_id)   # while the grid is read
            columns, rows = self._grid(workspace_id, item_id, link_column,
                                       lambda link, title: {"link": link, "title": title, "url": link_page(client.base_url, client.tenant, link)})
            product, values = named.result()
        current = values.get(field_id)
        primary = None
        if _has_value(current):
            primary = {"link": _link_of(current), "title": display_text(current).strip()}
        return {"product": product, "primary": primary, "link_column": link_column, "columns": columns, "rows": rows}

    def _grid(self, workspace_id: str, item_id: str, link_column: str,
              stand: Callable[[str, str], Dict[str, Any]]) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
        """The Grid tab of the product as ``(columns, rows)`` (see ``inspect``); ``stand(link, title)`` gives what each row says of the component
        it names. How a grid is laid out is read loosely."""
        base = f"{WORKSPACES}/{workspace_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            fields = pool.submit(WorkspaceService(self._client).grid_fields, base)   # while the rows are read
            data = self._client.get_json(f"{base}/items/{item_id}/views/{GRID_VIEW}/rows")
            laid_out = sorted(fields.result()[0], key=lambda f: f["order"])   # as Fusion Manage lays the columns out
        titles = {f["id"]: f["title"] for f in laid_out}
        columns: List[Dict[str, str]] = [{"id": f["id"], "title": f["title"]} for f in laid_out if f["shown"]]
        rows: List[Dict[str, Any]] = []
        for row in rows_in(data, "rows"):
            cells: Dict[str, str] = {}
            link = title = ""
            for cell in dict_rows(row.get("rowData")):
                if "/fields/" not in str(cell.get("__self__")):   # a cell that is not a column of the grid: the row's own id ("Row Id")
                    continue
                column = last_segment(cell.get("__self__"))
                value = cell.get("value")
                cells[column] = display_text(value).strip()
                if column == link_column and isinstance(value, dict):
                    link, title = str(value.get("link") or ""), display_text(value).strip()
                if column not in (c["id"] for c in columns):
                    columns.append({"id": column, "title": titles.get(column) or str(cell.get("title") or column)})
            rows.append({"id": last_segment(row.get("__self__")), "cells": cells, **stand(link, title)})
        return columns, rows

    def usage(self, workspace_id: str, number: str, field_id: str, link_column: str) -> Dict[str, Any]:
        """Where the component with ``number`` is used in the portfolio, whatever revision of it a product holds: as a product's Primary Component
        (``field_id``) or as a row of its Variants grid (``link_column``, "" when the grid is not set up, so variants are not looked for).

        ``{"number", "primary": [{"id", "number", "name", "url", "picture", "component"}], "variants": [... and "rows"], "variants_checked"}``:
        ``id`` is the product's item id, ``number`` and ``name`` its descriptor split in two, ``url`` the product's page in
        Fusion Manage, ``picture`` the link of the first picture it holds ("" when it has none; ``products_picture`` reads it), ``component``
        the link of the item that is its Primary Component ("" when it has none; the design it came from is what Fusion opens) and ``rows``
        how many rows of the grid hold the component. It reads the two fields of every product with the v1 search, which can read the Grid where the v3 search cannot, and
        compares them here by item number (``number_matches``). Raises ``FmApiError`` with the reason: a failed check is not "not used"."""
        fields = [Field(field_id)] + ([Field(link_column, GRIDVIEW)] if link_column else [])
        primary: Dict[str, None] = {}   # the ids of the products, in the order found
        variants: Dict[str, int] = {}   # the id of each product -> how many rows of its Variants grid hold the component
        primary_key, column_key = field_id.upper(), link_column.upper()
        for row in self._v1_rows(workspace_id, fields, [Sort(field_id)]):   # sorted on an Item Details field: the service needs a sort
            for key, text in row.entries:
                if not text or not number_matches(text, number):
                    continue
                if key.upper() == primary_key:
                    primary[row.dms_id] = None
                elif key.upper() == column_key:
                    variants[row.dms_id] = variants.get(row.dms_id, 0) + 1
        service = ItemService(self._client)
        cards = {}
        for item in dict.fromkeys([*primary, *variants]):
            descriptor, values = service.read_named(workspace_id, item)
            code, name = split_title(descriptor)
            cards[item] = {"id": item, "number": code, "name": name, "picture": _picture_link(values), "component": _link_of(values.get(field_id)),
                           "url": page_url(self._client.base_url, self._client.tenant, workspace_id, item)}
        log.info("Component %s is the Primary Component of %d product(s) and a variant of %d", number, len(primary), len(variants))
        return {"number": number, "variants_checked": bool(link_column), "primary": [cards[item] for item in primary],
                "variants": [{**cards[item], "rows": rows} for item, rows in variants.items()]}

    def _v1_rows(self, workspace_id: str, fields: List[Field], sort: List[Sort]) -> List[V1Row]:
        """The rows of a v1 search. Raises ``NotAllowed`` when Fusion Manage does not accept the user's app, else ``FmApiError`` with the reason.

        Seen: a Client ID with no user mapped to it is answered 401 by the v3 API but 500 by the v1 search, so a 500 is asked of v3 again."""
        try:
            return V1SearchService(self._client).rows(workspace_id, fields, sort)
        except FmApiError as exc:
            if exc.status in REFUSED or (exc.status >= 500 and self._app_not_accepted(workspace_id)):
                raise NotAllowed() from exc
            raise

    def _app_not_accepted(self, workspace_id: str) -> bool:
        """Whether the v3 API refuses the user's app: it reads the workspace's own page, which any user of the workspace may."""
        try:
            self._client.get_json(f"{WORKSPACES}/{workspace_id}")
        except FmApiError as exc:
            return exc.status in REFUSED
        return False

    def update_variant(self, workspace_id: str, item_id: str, row_id: str, number: str, link_column: str) -> Dict[str, Any]:
        """Change the component of the row ``row_id`` of the Variants grid to the revision of ``number`` that is to be assigned (see ``assign``): the
        same item number in another revision. Answers ``{"status": "updated", "component"}``. Raises ``FmApiError`` with the reason."""
        _, chosen = self._options_of(workspace_id, link_column, number, grid=True)
        scope = f"{WORKSPACES}/{workspace_id}/views/{GRID_VIEW}/fields"
        row = {"rowData": [{"__self__": f"{scope}/{link_column}", "value": {"link": chosen.link}}]}
        self._send_row("PUT", f"{WORKSPACES}/{workspace_id}/items/{item_id}/views/{GRID_VIEW}/rows/{row_id}", row)
        return {"status": UPDATED, "number": number, "component": chosen.link}

    def _add_variant(self, workspace_id: str, item_id: str, number: str, link_column: str, chosen: Candidate, row_values: Dict[str, Any]) -> None:
        """Add the component (the revision ``chosen``) as a row of the product's Grid tab, in the column that links to the components."""
        hits, _ = self._options_of(workspace_id, link_column, number, grid=True)
        same = [c for c in hits if (c.title, c.version) == (chosen.title, chosen.version)]   # the same revision, in the column's own picklist
        if len(same) != 1:
            raise FmApiError(t("app.product_variant_revision", title=f"{chosen.title} {chosen.version}".strip(), column=link_column))
        self._post_variant(workspace_id, item_id, link_column, same[0].link, row_values)

    def _post_variant(self, workspace_id: str, item_id: str, link_column: str, link: str, row_values: Dict[str, Any]) -> None:
        """Add a row to the product's Grid tab whose ``link_column`` links to the component at ``link`` and whose other columns hold ``row_values``
        (a blank is left out; a picklist option is sent as a link to it)."""
        scope = f"{WORKSPACES}/{workspace_id}/views/{GRID_VIEW}/fields"
        cells = [{"__self__": f"{scope}/{link_column}", "value": {"link": link}}]
        cells += [{"__self__": f"{scope}/{column}", "value": field_value(value)}
                  for column, value in row_values.items() if column != link_column and value not in (None, "", [], {})]
        self._send_row("POST", f"{WORKSPACES}/{workspace_id}/items/{item_id}/views/{GRID_VIEW}/rows", {"rowData": cells})

    def _send_row(self, method: str, url: str, row: Dict[str, Any]) -> None:
        """Send a row of the Grid tab. Raises ``FmApiError`` with what Fusion Manage said."""
        try:
            self._client.send_json(method, url, row)
        except FmApiError as exc:
            log.warning("%s of a row to %s failed: %s; body %s", method, url, exc, row)
            raise self._refused(exc) from exc

    @staticmethod
    def _refused(exc: FmApiError) -> FmApiError:
        """What Fusion Manage said of the row, in words (the panel shows a plain 400 as a bad search, which it was not)."""
        reason = str(read_refusal(exc, set(), "")) if exc.body else str(exc)
        return FmApiError(t("app.product_variant_refused", reason=reason), exc.status if exc.status != BAD_REQUEST else UNPROCESSABLE)

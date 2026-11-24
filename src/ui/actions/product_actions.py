"""Palette actions of the Assign Product panel: the views of the Portfolio Management workspace, their rows, the form for a new product, and creating one.

They are read and written on a worker thread and the panel polls ``products_status`` for the answer, as the Add Items picker does
(``PickerReads``): Fusion's palette handler never waits on the network.
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set, Tuple

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.hub_context import HubContexts
from ...config.workspace_models import KINDS_BY_ID, PORTFOLIO_KIND, WorkspaceConfig, kind_texts
from ...core.i18n import t
from ...core.shapes import whole
from ...fm.client import FmClient
from ...fm.components import LINEAGE, ComponentService
from ...fm.item_view import ItemViewService
from ...fm.permissions import ADD_ITEMS, granted, may
from ...fm.workspace_form import WorkspaceFormService
from ...fm.tableaus import TableauService
from ...publish.products import REPLACE, REPLACE_MOVE, VARIANT, VARIANT_UPDATE, NotAllowed, ProductService
from ..item_number_error import NoItemNumber
from ..message_bridge import MessageBridge
from ..product_mode import PRODUCT_MODE
from .background import Runner, in_thread, why
from .design_number import OpenDesign
from .search_actions import PickerReads, answer_for, token_of

if TYPE_CHECKING:   # only for the type: importing it loads Fusion's modules
    from ..item_numbers import DesignRef


def _text(payload: Dict[str, Any], key: str) -> str:
    """What the page sent under ``key``, as text ("" when it sent none)."""
    return str(payload.get(key) or "")


def _fusion_app() -> Any:
    import adsk.core   # Fusion's module is loaded when asked, so this file imports without Fusion
    return adsk.core.Application.get()


def open_design_file(payload: Dict[str, Any], app: Callable[[], Any] = _fusion_app) -> Dict[str, Any]:
    """Open the design whose data file has the lineage id ``file`` in Fusion. Runs on Fusion's thread. Raises ``ValueError`` with the reason when
    the id is not a design's, or the active hub has no such file (Fusion finds a file in the active hub only)."""
    file_id = str(payload.get("file") or "")
    if not LINEAGE.fullmatch(file_id):
        raise ValueError(t("app.design_file_bad"))
    fusion = app()
    found = fusion.data.findFileById(file_id)
    if found is None:
        raise ValueError(t("app.design_file_missing"))
    fusion.documents.open(found, True)
    return {}


NO_DESIGN = {"number": "", "name": "", "thumbnail_url": "", "revision": "", "state": ""}   # what ``design`` answers for a design that is not saved


class WorkspaceReads(PickerReads):
    """The reads of the panels that work with one workspace of the settings (``kind``): it finds the workspace and starts a read on it, or
    answers at once why it cannot be used."""

    kind = PORTFOLIO_KIND

    def _cfg(self) -> Optional[WorkspaceConfig]:
        """The settings of the workspace of this ``kind``, or None when none are set."""
        return self._config.config.workspaces.get(self.kind)

    def _problem(self, cfg: Optional[WorkspaceConfig]) -> str:
        """Why the workspace cannot be used ("" when it can): turned off, or not set."""
        if cfg and not cfg.enabled:
            return t("data.portfolio_off")
        return "" if cfg and cfg.workspace_id else t("app.products_not_set_up")

    def _in_workspace(self, payload: Dict[str, Any], work: Callable[[FmClient, str], Any], alongside: bool = False) -> Dict[str, Any]:
        """Start ``work(client, workspace)`` for the request, or answer at once that the workspace cannot be used."""
        token = token_of(payload)
        cfg = self._cfg()
        problem = self._problem(cfg)
        if problem:
            return answer_for(token, message=problem)
        workspace = str(cfg.workspace_id)
        return self._start(token, lambda client: work(client, workspace), alongside)


class ProductReads(WorkspaceReads):
    """The reads and the create of the Assign Product panel, one answer for each request token."""

    def __init__(self, config: ConfigService, make_client: Callable[[], FmClient], run: Runner = in_thread, design: Optional[OpenDesign] = None, *,
                 contexts: HubContexts) -> None:
        super().__init__(config, make_client, run)
        self._contexts = contexts   # gives the ``stamp`` the Item panel's tabs ask for
        self._design = design or OpenDesign()   # which design is open, and its item number

    def _automatic(self) -> Set[str]:
        """The ids of the fields the add-in fills in when a product is assigned: the Primary Component field."""
        cfg = self._cfg()
        return {cfg.component_field} if cfg and cfg.component_field else set()

    def views(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The views of the workspace, and whether the user may add items to it (the button to create a product needs it)."""
        return self._in_workspace(payload, lambda client, workspace: {
            **TableauService(client).views(workspace), "can_create": may(client, workspace, ADD_ITEMS)})

    def columns(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The columns of a view, for the header to show before its rows arrive."""
        view = _text(payload, "view")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).columns(workspace, view))

    def fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Every field a view of the portfolio workspace can be filtered by."""
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).available(workspace))

    def image(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The picture in an image field of one product, for a cell of the list."""
        item, field, number = (_text(payload, key) for key in ("item", "field", "number"))
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).image(workspace, item, field, number), alongside=True)

    def picture(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A picture a product holds, from the link its item gave for it (the form of an edit has the item already, so no read of it is repeated)."""
        link = _text(payload, "link")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).picture(workspace, link), alongside=True)

    def save_filters(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Save the filters of columns of a view: ``changes`` is ``[{"column", "match", "filters"}]``."""
        view = _text(payload, "view")
        changes = payload.get("changes") if isinstance(payload.get("changes"), list) else []
        columns = payload.get("columns") if isinstance(payload.get("columns"), list) else None   # the columns to show, in order; none: as they are
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).save_view_filters(workspace, view, changes, columns))

    def create_view(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make a view: ``name`` and the ``columns`` (field keys) it shows."""
        name = _text(payload, "name")
        columns = payload.get("columns") if isinstance(payload.get("columns"), list) else []
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).create_view(workspace, name, columns))

    def rename_view(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Give a view a new name."""
        view, name = _text(payload, "view"), _text(payload, "name")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).rename_view(workspace, view, name))

    def delete_view(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a view."""
        view = _text(payload, "view")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).delete_view(workspace, view))

    def rows(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A page of the rows of a view."""
        view, page, size = _text(payload, "view"), whole(payload.get("page")), whole(payload.get("size"))
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).rows(workspace, view, page, size))

    def form(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The form for a new product: the sections of the workspace and their fields."""
        return self._in_workspace(payload, lambda client, workspace: WorkspaceFormService(client).form(workspace, self._automatic()))

    def item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The values of one product, to fill the form of an edit."""
        item = _text(payload, "item")
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).read(workspace, item))

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Change a product to the values in the form."""
        item = _text(payload, "item")
        values = _values(payload)
        if not item or not values:
            return answer_for(token_of(payload), message=t("app.product_no_values"))
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).update(workspace, item, values))

    def _refusal(self, payload: Dict[str, Any], item: bool = True) -> Optional[Dict[str, Any]]:
        """The answer that says why a request about a product cannot start (no product chosen, or no Primary Component field set), or None."""
        if item and not _text(payload, "item"):
            return answer_for(token_of(payload), message=t("app.product_choose_first"))
        cfg = self._cfg()
        if not cfg or not cfg.component_field:
            return answer_for(token_of(payload), message=t("app.product_no_primary_field"))
        return None

    def assign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make the open design the Primary Component of a product (its latest released revision, else its working version), or, once the person
        has said so, replace the one it has or add it as a variant."""
        token = token_of(payload)
        item, mode = _text(payload, "item"), _text(payload, "mode")
        refusal = self._refusal(payload)
        if refusal:
            return refusal
        cfg = self._cfg()
        if mode in (VARIANT, REPLACE_MOVE, VARIANT_UPDATE) and not cfg.variants.link_column:
            return answer_for(token, message=t("app.product_no_variants_column"))
        if mode not in ("", REPLACE, VARIANT, REPLACE_MOVE, VARIANT_UPDATE):
            return answer_for(token, message=t("app.unknown_request"))
        ref, failed = self._open_design(token)
        if failed:
            return failed
        field, column = cfg.component_field, cfg.variants.link_column
        if mode == VARIANT_UPDATE:   # the revision of a row that holds the component already
            row_id = _text(payload, "row_id")
            if not row_id:
                return answer_for(token, message=t("app.unknown_request"))
            return self._in_workspace(payload, lambda client, workspace: ProductService(client).update_variant(
                workspace, item, row_id, self._design.number(ref), column))
        row = _values(payload, "row")   # the other columns of the variant row, when it is added
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).assign(
            workspace, item, self._design.number(ref), field, column, mode, row))

    def inspect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the product holds of components, and how the open design stands to it (its Primary Component and each row of the Variants grid)."""
        refusal = self._refusal(payload)
        if refusal:
            return refusal
        ref, failed = self._open_design(token_of(payload))
        if failed:
            return failed
        item, cfg = _text(payload, "item"), self._cfg()
        field, column = cfg.component_field, cfg.variants.link_column
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).inspect(
            workspace, item, self._design.number(ref), field, column))

    def view(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """One product as the Item panel shows an item: its title, workflow state, tabs and every section of fields, read by ``ItemViewService``.
        ``stamp`` is what the page sends with the look-ups of the tabs (the Item panel's own); ``tabs["grid"]`` is the Grid tab, named as the
        workspace names it, when it has one. The workspace's layout is read again each time, as for the Item panel."""
        item = _text(payload, "item")
        if not item:
            return answer_for(token_of(payload), message=t("app.product_choose_first"))

        def look(client: FmClient, workspace: str) -> Dict[str, Any]:
            context, reason = self._contexts.attempt()
            if context is None:
                raise ValueError(reason)
            ItemViewService.forget()   # opening a product, or reading it again, asks for the workspace's layout again, as the Item panel does
            view = ItemViewService(client).read(workspace, item, granted(client, workspace), with_grid=True, pictures=False)
            view["stamp"] = context.stamp
            return view

        return self._in_workspace(payload, look, alongside=True)   # with the contents: the product's head and its grid are read together

    def contents(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """What one product holds of components, for browsing: its Primary Component and the rows of its Variants grid (see ``ProductService.contents``)."""
        refusal = self._refusal(payload)
        if refusal:
            return refusal
        item, cfg = _text(payload, "item"), self._cfg()
        field, column = cfg.component_field, cfg.variants.link_column
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).contents(workspace, item, field, column), alongside=True)

    def usage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Where the open design is used in the portfolio: as a Primary Component, as a variant, or not at all (see ``ProductService.usage``).
        A design with no item number is answered ``{"unpublished": True, "message"}``: it is not in Fusion Manage, which is not an error."""
        refusal = self._refusal(payload, item=False)
        if refusal:
            return refusal
        ref, failed = self._open_design(token_of(payload))
        if failed:
            return failed
        cfg = self._cfg()
        field, column = cfg.component_field, cfg.variants.link_column

        def look(client: FmClient, workspace: str) -> Dict[str, Any]:
            try:
                number = self._design.number(ref)
            except NoItemNumber as exc:
                return {"unpublished": True, "message": str(exc)}
            try:
                return ProductService(client).usage(workspace, number, field, column)
            except NotAllowed:   # not an error either: the page says so in place of the cards, as the Item panel does
                return {"denied": t("app.no_view_permission", workspace=kind_texts(KINDS_BY_ID[PORTFOLIO_KIND])[0])}

        return self._in_workspace(payload, look, alongside=True)

    def design_file(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The lineage id of the design a component item was published from (see ``ComponentService.design_file``), for ``products_open_file``."""
        link = _text(payload, "link")
        return self._start(token_of(payload), lambda client: {"file": ComponentService(client).design_file(link)}, alongside=True)

    def design(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The open design, for the head of the page: its name, item number and thumbnail from the Data Model, and the revision and life cycle state
        of the item it has in Fusion Manage (blank when the design has no item there yet)."""
        token = token_of(payload)
        ref, failed = self._open_design(token)
        if failed:
            return failed

        def look(client: FmClient) -> Dict[str, Any]:
            try:
                details = dict(self._design.describe(ref))
            except NoItemNumber:
                return dict(NO_DESIGN)
            link = self._design.record_link(ref)
            revision, state = ComponentService(client).revision_and_state(link) if link else ("", "")
            return {**details, "revision": revision, "state": state}

        return self._start(token, look, alongside=True)

    def _open_design(self, token: str) -> Tuple[Optional["DesignRef"], Optional[Dict[str, Any]]]:
        """``(reference of the open design, None)``, or ``(None, the answer that says it could not be read)``. Fusion's thread."""
        try:
            return self._design.ref(), None
        except Exception as exc:  # noqa: BLE001 - the panel is told, not left waiting
            return None, answer_for(token, message=why(exc))

    def variant_form(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The columns of the Variants grid that a person can fill in for the row added (the column that links the component is not one)."""
        cfg = self._cfg()
        column = cfg.variants.link_column if cfg else ""
        return self._in_workspace(payload, lambda client, workspace: WorkspaceFormService(client).grid_form(workspace, column))

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a product with the values filled in."""
        values = _values(payload)
        if not values:
            return answer_for(token_of(payload), message=t("app.product_no_values"))
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).create(workspace, values))


def _values(payload: Dict[str, Any], key: str = "values") -> Dict[str, Any]:
    """The values the form sent (``{field id: value}``); empty when it sent none, or only blanks."""
    values = payload.get(key)
    values = {str(k): v for k, v in values.items()} if isinstance(values, dict) else {}
    return values if any(v is not None and str(v).strip() for v in values.values()) else {}


def register_product_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the actions of the panel: ``products_*`` for views, columns, fields (every field a view can be filtered by), filter (save), rows, form, options (a page
    of the items a linked field may take), create, item (the values of one product), update and assign (the open design to a product), and ``products_status`` to poll for an answer."""
    reads = ProductReads(config, lambda: FmClient(config.effective_settings(), auth), contexts=HubContexts(config, auth.session))
    bridge.register("products_views", reads.views)
    bridge.register("products_columns", reads.columns)
    bridge.register("products_fields", reads.fields)
    bridge.register("products_image", reads.image)
    bridge.register("products_picture", reads.picture)
    bridge.register("products_design", reads.design)
    bridge.register("products_design_file", reads.design_file)
    bridge.register("products_open_file", open_design_file)
    bridge.register("products_filter", reads.save_filters)
    bridge.register("products_create_view", reads.create_view)
    bridge.register("products_rename_view", reads.rename_view)
    bridge.register("products_delete_view", reads.delete_view)
    bridge.register("products_rows", reads.rows)
    bridge.register("products_form", reads.form)
    bridge.register("products_options", reads.options)
    bridge.register("products_variant_form", reads.variant_form)
    bridge.register("products_inspect", reads.inspect)
    bridge.register("products_usage", reads.usage)
    bridge.register("products_view", reads.view)
    bridge.register("products_contents", reads.contents)
    bridge.register("products_mode", lambda _payload: {"mode": PRODUCT_MODE.mode})   # the way the window was opened: see ``product_mode``
    bridge.register("products_create", reads.create)
    bridge.register("products_item", reads.item)
    bridge.register("products_update", reads.update)
    bridge.register("products_assign", reads.assign)
    bridge.register("products_status", reads.status)

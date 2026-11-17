"""Palette actions of the Assign Product panel: the views of the Portfolio Management workspace, their rows, the form for a new product, and creating one.

They are read and written on a worker thread and the panel polls ``products_status`` for the answer, as the Add Items picker does
(``PickerReads``): Fusion's palette handler never waits on the network.
"""

from typing import Any, Callable, Dict, Optional

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.workspace_models import PORTFOLIO_KIND, WorkspaceConfig
from ...core.i18n import t
from ...core.shapes import whole
from ...fm.client import FmClient
from ...fm.permissions import ADD_ITEMS, may
from ...fm.workspace_form import WorkspaceFormService
from ...fm.tableaus import TableauService
from ...publish.products import REPLACE, REPLACE_MOVE, VARIANT, VARIANT_UPDATE, ProductService
from ..message_bridge import MessageBridge
from .background import Runner, in_thread, why
from .design_number import OpenDesign
from .search_actions import PickerReads, answer_for, token_of


class ProductReads(PickerReads):
    """The reads and the create of the Assign Product panel, one answer for each request token."""

    def __init__(self, config: ConfigService, make_client: Callable[[], FmClient], run: Runner = in_thread, design: Any = None) -> None:
        super().__init__(config, make_client, run)
        self._design = design or OpenDesign()   # which design is open, and its item number

    def _cfg(self) -> Optional[WorkspaceConfig]:
        return self._config.config.workspaces.get(PORTFOLIO_KIND)

    def _in_workspace(self, payload: Dict[str, Any], work: Callable[[FmClient, str], Any], alongside: bool = False) -> Dict[str, Any]:
        """Start ``work(client, workspace)`` for the request, or answer at once that no Portfolio Management workspace is set up."""
        token = token_of(payload)
        cfg = self._cfg()
        if cfg and not cfg.enabled:
            return answer_for(token, message=t("data.portfolio_off"))
        workspace = str(cfg.workspace_id) if cfg and cfg.workspace_id else ""
        if not workspace:
            return answer_for(token, message=t("app.products_not_set_up"))
        return self._start(token, lambda client: work(client, workspace), alongside)

    def _automatic(self) -> set:
        """The ids of the fields the add-in fills in when a product is assigned: the Primary Component field."""
        cfg = self._cfg()
        return {cfg.component_field} if cfg and cfg.component_field else set()

    def views(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The views of the workspace, and whether the user may add items to it (the button to create a product needs it)."""
        return self._in_workspace(payload, lambda client, workspace: {
            **TableauService(client).views(workspace), "can_create": may(client, workspace, ADD_ITEMS)})

    def columns(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The columns of a view, for the header to show before its rows arrive."""
        view = str(payload.get("view") or "")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).columns(workspace, view))

    def fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Every field a view of the portfolio workspace can be filtered by."""
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).available(workspace))

    def image(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The picture in an image field of one product, for a cell of the list."""
        item, field, number = (str(payload.get(key) or "") for key in ("item", "field", "number"))
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).image(workspace, item, field, number), alongside=True)

    def picture(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A picture a product holds, from the link its item gave for it (the form of an edit has the item already, so no read of it is repeated)."""
        link = str(payload.get("link") or "")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).picture(workspace, link), alongside=True)

    def save_filters(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Save the filters of columns of a view: ``changes`` is ``[{"column", "match", "filters"}]``."""
        view = str(payload.get("view") or "")
        changes = payload.get("changes") if isinstance(payload.get("changes"), list) else []
        columns = payload.get("columns") if isinstance(payload.get("columns"), list) else None   # the columns to show, in order; none: as they are
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).save_view_filters(workspace, view, changes, columns))

    def create_view(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make a view: ``name`` and the ``columns`` (field keys) it shows."""
        name = str(payload.get("name") or "")
        columns = payload.get("columns") if isinstance(payload.get("columns"), list) else []
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).create_view(workspace, name, columns))

    def rename_view(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Give a view a new name."""
        view, name = str(payload.get("view") or ""), str(payload.get("name") or "")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).rename_view(workspace, view, name))

    def delete_view(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a view."""
        view = str(payload.get("view") or "")
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).delete_view(workspace, view))

    def rows(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A page of the rows of a view."""
        view, page, size = str(payload.get("view") or ""), whole(payload.get("page")), whole(payload.get("size"))
        return self._in_workspace(payload, lambda client, workspace: TableauService(client).rows(workspace, view, page, size))

    def form(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The form for a new product: the sections of the workspace and their fields."""
        return self._in_workspace(payload, lambda client, workspace: WorkspaceFormService(client).form(workspace, self._automatic()))

    def item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The values of one product, to fill the form of an edit."""
        item = str(payload.get("item") or "")
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).read(workspace, item))

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Change a product to the values in the form."""
        item = str(payload.get("item") or "")
        values = _values(payload)
        if not item or not values:
            return answer_for(token_of(payload), message=t("app.product_no_values"))
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).update(workspace, item, values))

    def assign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make the open design the Primary Component of a product (its latest released revision, else its working version), or, once the person
        has said so, replace the one it has or add it as a variant."""
        token = token_of(payload)
        item, mode = (str(payload.get(key) or "") for key in ("item", "mode"))
        cfg = self._cfg()
        if not item:
            return answer_for(token, message=t("app.product_choose_first"))
        if not cfg or not cfg.component_field:
            return answer_for(token, message=t("app.product_no_primary_field"))
        if mode in (VARIANT, REPLACE_MOVE, VARIANT_UPDATE) and not cfg.variants.link_column:
            return answer_for(token, message=t("app.product_no_variants_column"))
        if mode not in ("", REPLACE, VARIANT, REPLACE_MOVE, VARIANT_UPDATE):
            return answer_for(token, message=t("app.unknown_request"))
        try:
            ref = self._design.ref()
        except Exception as exc:  # noqa: BLE001 - the panel is told, not left waiting
            return answer_for(token, message=why(exc))
        field, column = cfg.component_field, cfg.variants.link_column
        if mode == VARIANT_UPDATE:   # the revision of a row that holds the component already
            row_id = str(payload.get("row_id") or "")
            if not row_id:
                return answer_for(token, message=t("app.unknown_request"))
            return self._in_workspace(payload, lambda client, workspace: ProductService(client).update_variant(
                workspace, item, row_id, self._design.number(ref), column))
        row = _values(payload, "row")   # the other columns of the variant row, when it is added
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).assign(
            workspace, item, self._design.number(ref), field, column, mode, row))

    def inspect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the product holds of components, and how the open design stands to it (its Primary Component and each row of the Variants grid)."""
        item = str(payload.get("item") or "")
        cfg = self._cfg()
        token = token_of(payload)
        if not item:
            return answer_for(token, message=t("app.product_choose_first"))
        if not cfg or not cfg.component_field:
            return answer_for(token, message=t("app.product_no_primary_field"))
        try:
            ref = self._design.ref()
        except Exception as exc:  # noqa: BLE001 - the panel is told, not left waiting
            return answer_for(token, message=why(exc))
        field, column = cfg.component_field, cfg.variants.link_column
        return self._in_workspace(payload, lambda client, workspace: ProductService(client).inspect(
            workspace, item, self._design.number(ref), field, column))

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
    reads = ProductReads(config, lambda: FmClient(config.effective_settings(), auth))
    bridge.register("products_views", reads.views)
    bridge.register("products_columns", reads.columns)
    bridge.register("products_fields", reads.fields)
    bridge.register("products_image", reads.image)
    bridge.register("products_picture", reads.picture)
    bridge.register("products_filter", reads.save_filters)
    bridge.register("products_create_view", reads.create_view)
    bridge.register("products_rename_view", reads.rename_view)
    bridge.register("products_delete_view", reads.delete_view)
    bridge.register("products_rows", reads.rows)
    bridge.register("products_form", reads.form)
    bridge.register("products_options", reads.options)
    bridge.register("products_variant_form", reads.variant_form)
    bridge.register("products_inspect", reads.inspect)
    bridge.register("products_create", reads.create)
    bridge.register("products_item", reads.item)
    bridge.register("products_update", reads.update)
    bridge.register("products_assign", reads.assign)
    bridge.register("products_status", reads.status)

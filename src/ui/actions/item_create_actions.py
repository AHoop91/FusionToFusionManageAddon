"""Palette actions of the side panel of the Publish panel's structure viewer: a new manufacturing item, and a bought version of an item.

Like the Assign Product panel's (``product_actions``), each runs on a worker thread and the panel polls ``items_status`` with the request's
``token`` for the answer: ``{token, pending, ok, result, message, fields}``. ``result`` is what ``publish.bought_items.BoughtItems`` answers (see
the note ``dev/publish-item-flow.md``); a refusal says ``message`` for the form and ``fields`` (``{field id: message}``) for the fields it names.
The options of a picklist or link field are read with ``search_options`` and its ``search_status``, as the Add Items picker does.
"""

from typing import Any, Dict, Optional

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.workspace_models import ITEMS_KIND, WorkspaceConfig
from ...core.i18n import t
from ...fm.client import FmClient
from ...fm.permissions import ADD_ITEMS, may
from ...publish.bought_items import BoughtItems
from ..message_bridge import MessageBridge
from .product_actions import WorkspaceReads, _text, _values
from .search_actions import answer_for, token_of

ASSEMBLY = "assembly"   # the kind of item ``items_form`` gives the form of


class ItemCreateReads(WorkspaceReads):
    """The reads and the creates of the side panel, one answer for each request token."""

    kind = ITEMS_KIND

    def _problem(self, cfg: Optional[WorkspaceConfig]) -> str:
        """Why the Items workspace cannot be used ("" when it can): turned off, not set, or its settings are not complete."""
        return self._config.items_setup_problem()

    def form(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The form for a new manufacturing item: ``{form, fixed, number_field, can_create}`` (``can_create``: the user may add items)."""
        if _text(payload, "kind") != ASSEMBLY:
            return answer_for(token_of(payload), message=t("app.unknown_request"))
        cfg = self._cfg()
        return self._in_workspace(payload, lambda client, workspace: {
            **BoughtItems(client, workspace, cfg).assembly_form(), "can_create": may(client, workspace, ADD_ITEMS)})

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a manufacturing item from the values in the form: ``{id, link, number}``."""
        values = _values(payload)
        if not values:
            return answer_for(token_of(payload), message=t("app.product_no_values"))
        cfg = self._cfg()
        return self._in_workspace(payload, lambda client, workspace: BoughtItems(client, workspace, cfg).create_assembly(values))

    def bought_form(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The form for a bought version of the item ``source_id``, or the one numbered ``source_number`` (one of the two): ``{form, number,
        values, copied, skipped, fixed, can_create}``."""
        source, number = _text(payload, "source_id"), _text(payload, "source_number")
        cfg = self._cfg()
        return self._in_workspace(payload, lambda client, workspace: {
            **BoughtItems(client, workspace, cfg).bought_form(source, number), "can_create": may(client, workspace, ADD_ITEMS)})

    def bought_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create the bought version of the item ``source_id`` or ``source_number`` from the values in the form: ``{id, link, number}``."""
        source, number = _text(payload, "source_id"), _text(payload, "source_number")
        values = _values(payload)
        cfg = self._cfg()
        return self._in_workspace(payload, lambda client, workspace: BoughtItems(client, workspace, cfg).create_bought(source, values, number))

    def bought_find(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The bought version of the item numbered ``source_number`` that Fusion Manage has already: ``{found: {id, link, number, name} or null}``."""
        number = _text(payload, "source_number")
        cfg = self._cfg()
        return self._in_workspace(payload, lambda client, workspace: BoughtItems(client, workspace, cfg).find_bought(number))

def register_item_create_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register ``items_form`` and ``items_create`` (a new manufacturing item), ``bought_form`` and ``bought_create`` (a bought version of an
    item), ``bought_find`` (the one of an item, if any) and ``items_status`` to poll for their answers."""
    reads = ItemCreateReads(config, lambda: FmClient(config.effective_settings(), auth))
    bridge.register("items_form", reads.form)
    bridge.register("items_create", reads.create)
    bridge.register("bought_form", reads.bought_form)
    bridge.register("bought_create", reads.bought_create)
    bridge.register("bought_find", reads.bought_find)
    bridge.register("items_status", reads.status)

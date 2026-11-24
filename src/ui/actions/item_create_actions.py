"""Palette actions of the side panel of the Publish panel's structure viewer: a new manufacturing item, and a bought version of an item.

Like the Assign Product panel's (``product_actions``), each runs on a worker thread and the panel polls ``items_status`` with the request's
``token`` for the answer: ``{token, pending, ok, result, message, fields}``. ``result`` is what ``publish.bought_items.BoughtItems`` answers (see
the note ``dev/publish-item-flow.md``; ``bought_open`` is one request for what a bought version's dialog shows); a refusal says ``message`` for the form and ``fields`` (``{field id: message}``) for the fields it names.
The options of a picklist or link field are read with ``search_options`` and its ``search_status``, as the Add Items picker does.
"""

from typing import Any, Callable, Dict, Optional

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.workspace_models import ITEMS_KIND, WorkspaceConfig
from ...core.i18n import t
from ...fm.client import FmClient
from ...fm.permissions import ADD_ITEMS, may
from ...publish.bought_items import BoughtItems
from ..message_bridge import MessageBridge
from .background import Runner, in_thread
from .product_actions import WorkspaceReads, _text, _values
from .search_actions import answer_for, token_of

ASSEMBLY = "assembly"   # the kind of item ``items_form`` gives the form of


class ItemCreateReads(WorkspaceReads):
    """The reads and the creates of the side panel, one answer for each request token."""

    kind = ITEMS_KIND

    def _problem(self, cfg: Optional[WorkspaceConfig]) -> str:
        """Why the Items workspace cannot be used ("" when it can): turned off, not set, or its settings are not complete. ``cfg`` is not needed: the
        config service reads the same settings."""
        return self._config.items_setup_problem()

    def form(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The form for a new manufacturing item: ``{form, locked, number_field, can_create}`` (``can_create``: the user may add items)."""
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

    def bought_open(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the dialog of a bought version of an EBOM line shows: ``{found: {id, link, number, name, url}}`` (the bought version there is already) or the
        form, ``{form, number, number_field, values, locked, source_id, can_create}`` (see ``BoughtItems.open``). The line is given by its ``source_number``:
        the item of the Items workspace is found by it (the Data Model's link of a component names its Components record, not that item)."""
        number = _text(payload, "source_number")
        cfg = self._cfg()

        def work(client: FmClient, workspace: str) -> Dict[str, Any]:
            answer = BoughtItems(client, workspace, cfg).open("", number)
            return answer if "found" in answer else {**answer, "can_create": may(client, workspace, ADD_ITEMS)}
        return self._in_workspace(payload, work)

    def bought_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create the bought version of the item ``source_id`` or ``source_number`` from the values in the form: ``{id, link, number}``."""
        source, number = _text(payload, "source_id"), _text(payload, "source_number")
        values = _values(payload)
        cfg = self._cfg()
        return self._in_workspace(payload, lambda client, workspace: BoughtItems(client, workspace, cfg).create_bought(source, values, number))


def register_item_create_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register ``items_form`` and ``items_create`` (a new manufacturing item), ``bought_open`` and ``bought_create`` (a bought version of an
    item: what its dialog shows, and the create) and ``items_status`` to poll for their answers."""
    reads = ItemCreateReads(config, lambda: FmClient(config.effective_settings(), auth))
    bridge.register("items_form", reads.form)
    bridge.register("items_create", reads.create)
    bridge.register("bought_open", reads.bought_open)
    bridge.register("bought_create", reads.bought_create)
    bridge.register("items_status", reads.status)

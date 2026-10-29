"""Palette actions that find the Fusion Manage tenant from the open design's linked item."""

from typing import Any, Callable, Dict, Tuple

from ...config.hub import tenant_of_link
from ...core.logging_setup import get_logger
from ...fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ...fusion_mfg.model_service import read_manage_item, read_section
from ..message_bridge import MessageBridge
from .background import BackgroundRead, Runner, in_thread
from .design_ref import model_ref

log = get_logger("tenant_actions")

ACTION = "detect_tenant_status"
NO_DESIGN = "Open a design that is linked to a Fusion Manage item, then try again."
NOT_LINKED = "The open design is not linked to a Fusion Manage item. Open a design that is, then try again."


class NoDesign(Exception):
    """No saved design is open, so there is no item to find the tenant from."""


def register_tenant_actions(bridge: MessageBridge, open_model_ref: Callable[[], Tuple[str, str]] = model_ref,
                            run: Runner = in_thread) -> None:
    """Register ``detect_tenant`` and ``detect_tenant_status``.

    The Data Model knows the Fusion Manage item the open design is linked to, and that item's address names the tenant. The read
    runs on a worker thread, which pushes the answer to the panel when it is done, so Fusion's UI thread is never blocked.
    ``open_model_ref`` gives ``(model id, timestamp)`` of the open design (on Fusion's thread), and ``run`` starts the read on a worker.
    """
    reads = BackgroundRead(bridge, ACTION, {"tenant": ""}, run)

    def prepare() -> Callable[[], Dict[str, Any]]:
        model_id, saved_at = open_model_ref()
        if not model_id:
            raise NoDesign(NO_DESIGN)
        client = FusionGraphQlClient()

        def work() -> Dict[str, Any]:
            summary = read_section(client, "summary", model_id, saved_at)
            link = read_manage_item(client, summary, summary.get("component_id", ""), saved_at)
            tenant = tenant_of_link(link["urn"], link["url"])
            log.info("Tenant found from the open design's Fusion Manage item: %r", tenant)
            return {"ok": bool(tenant), "tenant": tenant, "message": "" if tenant else NOT_LINKED}
        return work

    def detect_tenant(_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return reads.start(prepare)
        except NoDesign as exc:
            return reads.failure(str(exc))

    bridge.register("detect_tenant", detect_tenant)
    bridge.register(ACTION, lambda _payload: reads.status())

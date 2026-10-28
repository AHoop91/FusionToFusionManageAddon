"""Palette actions that find the Fusion Manage tenant from the open design's linked item."""

import threading
from typing import Any, Dict

from ...config.hub import tenant_of_link
from ...core.logging_setup import get_logger
from ...fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ...fusion_mfg.model_service import read_manage_item, read_section
from ..message_bridge import MessageBridge
from .design_ref import model_ref

log = get_logger("tenant_actions")

NOT_LINKED = "The open design is not linked to a Fusion Manage item. Open a design that is, then try again."


def register_tenant_actions(bridge: MessageBridge) -> None:
    """Register ``detect_tenant`` and ``detect_tenant_status``.

    The Data Model knows the Fusion Manage item the open design is linked to, and that item's address names the tenant. The read
    runs on a worker thread, which pushes the answer to the panel when it is done, so Fusion's UI thread is never blocked.
    """

    state: Dict[str, Any] = {"pending": False, "ok": False, "tenant": "", "message": ""}
    lock = threading.Lock()

    def run(client: FusionGraphQlClient, model_id: str, time: str) -> None:
        try:
            summary = read_section(client, "summary", model_id, time)
            link = read_manage_item(client, summary, summary.get("component_id", ""), time)
            tenant = tenant_of_link(link["urn"], link["url"])
            log.info("Tenant found from the open design's Fusion Manage item: %r", tenant)
            outcome = {"pending": False, "ok": bool(tenant), "tenant": tenant, "message": "" if tenant else NOT_LINKED}
        except Exception as exc:  # noqa: BLE001 - never leave the panel waiting
            log.exception("Could not find the tenant")
            outcome = {"pending": False, "ok": False, "tenant": "", "message": str(exc) or type(exc).__name__}
        with lock:
            state.update(outcome)
        bridge.push("detect_tenant_status", outcome)   # the panel is told, not left to ask

    def detect_tenant(_payload: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            if state["pending"]:
                return dict(state)
        model_id, time = model_ref()
        if not model_id:
            return {"pending": False, "ok": False, "tenant": "", "message": "Open a design that is linked to a Fusion Manage item, then try again."}
        client = FusionGraphQlClient()
        with lock:
            state.update(pending=True, ok=False, tenant="", message="")
            snapshot = dict(state)
        threading.Thread(target=run, args=(client, model_id, time), daemon=True).start()
        return snapshot

    def detect_tenant_status(_payload: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            return dict(state)

    bridge.register("detect_tenant", detect_tenant)
    bridge.register("detect_tenant_status", detect_tenant_status)

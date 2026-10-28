"""Palette actions that list the hub's custom properties for field mapping."""

import threading
from typing import Any, Dict

from ...config.config_service import CompanyModeUnavailable
from ...fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ...fusion_mfg.properties import PropertyService
from ...core.logging_setup import get_logger
from ..message_bridge import MessageBridge

log = get_logger("property_actions")


def _active_hub_name() -> str:
    """Name of the hub open in Fusion. Must run on Fusion's UI thread."""
    import adsk.core
    hub = adsk.core.Application.get().data.activeHub
    return hub.name if hub else ""


def register_property_actions(bridge: MessageBridge) -> None:
    """Register ``list_custom_properties`` and ``list_custom_properties_status``.

    Like workspace validation, the query runs on a worker thread, which pushes the answer to the panel when it is done, so Fusion's UI
    thread is never blocked.
    """

    state: Dict[str, Any] = {"pending": False, "ok": False, "properties": [], "message": ""}
    lock = threading.Lock()

    def run(client: FusionGraphQlClient, hub_name: str) -> None:
        try:
            properties = PropertyService(client).list_properties(hub_name)
            log.info("Properties loaded for hub '%s': %d", hub_name, len(properties))
            outcome = {"pending": False, "ok": True, "properties": properties, "message": ""}
        except Exception as exc:  # never leave the panel waiting
            log.exception("Custom property load failed for hub '%s'", hub_name)
            outcome = {"pending": False, "ok": False, "properties": [], "message": str(exc) or type(exc).__name__}
        with lock:
            state.update(outcome)
        bridge.push("list_custom_properties_status", outcome)   # the panel is told, not left to ask

    def list_custom_properties(_payload: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            if state["pending"]:
                return dict(state)
        try:
            client = FusionGraphQlClient()
            hub_name = _active_hub_name()
        except CompanyModeUnavailable as exc:
            return {"pending": False, "ok": False, "properties": [], "message": str(exc)}
        except Exception as exc:
            log.exception("Could not start the custom property load")
            return {"pending": False, "ok": False, "properties": [], "message": f"No active hub: {exc}"}
        log.info("Loading custom properties for active hub '%s'", hub_name)
        with lock:
            state.update(pending=True, ok=False, properties=[], message="")
            snapshot = dict(state)
        threading.Thread(target=run, args=(client, hub_name), daemon=True).start()
        return snapshot

    def list_custom_properties_status(_payload: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            return dict(state)

    bridge.register("list_custom_properties", list_custom_properties)
    bridge.register("list_custom_properties_status", list_custom_properties_status)

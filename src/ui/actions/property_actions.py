"""Palette actions that list the hub's custom properties for field mapping."""

from typing import Any, Callable, Dict

from ...config.config_service import CompanyModeUnavailable
from ...core.logging_setup import get_logger
from ...fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ...fusion_mfg.properties import PropertyService
from ..message_bridge import MessageBridge
from .background import BackgroundRead, Runner, in_thread

log = get_logger("property_actions")

ACTION = "list_custom_properties_status"


def _active_hub_name() -> str:
    """Name of the hub open in Fusion. Must run on Fusion's UI thread."""
    import adsk.core
    hub = adsk.core.Application.get().data.activeHub
    return hub.name if hub else ""


def register_property_actions(bridge: MessageBridge, hub_name: Callable[[], str] = _active_hub_name, run: Runner = in_thread) -> None:
    """Register ``list_custom_properties`` and ``list_custom_properties_status``.

    Like workspace validation, the query runs on a worker thread, which pushes the answer to the panel when it is done, so Fusion's UI
    thread is never blocked. ``hub_name`` gives the name of the open hub (on Fusion's thread), and ``run`` starts the read on a worker.
    """
    reads = BackgroundRead(bridge, ACTION, {"properties": []}, run)

    def prepare() -> Callable[[], Dict[str, Any]]:
        client, name = FusionGraphQlClient(), hub_name()
        log.info("Loading custom properties for active hub '%s'", name)

        def work() -> Dict[str, Any]:
            properties = PropertyService(client).list_properties(name)
            log.info("Properties loaded for hub '%s': %d", name, len(properties))
            return {"properties": properties}
        return work

    def list_custom_properties(_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return reads.start(prepare)
        except CompanyModeUnavailable as exc:
            return reads.failure(str(exc))
        except Exception as exc:  # noqa: BLE001 - what Fusion says when no hub is open, or there is no Fusion to ask
            log.exception("Could not start the custom property load")
            return reads.failure(f"No active hub: {exc}")

    bridge.register("list_custom_properties", list_custom_properties)
    bridge.register(ACTION, lambda _payload: reads.status())

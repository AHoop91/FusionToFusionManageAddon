"""Palette actions for the Publish Item panel: loading the open design's sections, opening links, and saying which design is open.

The sections and how each is loaded are in ``publish.panel_sections``.
"""

import webbrowser
from typing import Any, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...publish.panel_sections import PublishSections
from ..message_bridge import MessageBridge
from .design_ref import model_ref


def register_publish_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the section load handlers.

    Queries run on worker threads and the panel polls for the answer, so
    Fusion's UI thread is never blocked. Loaded sections are kept for the
    open design, so switching back to a tab does not query again.
    """
    sections = PublishSections(config, auth, model_ref)

    def open_url(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open a link in the system browser (a palette cannot open one itself). https, or http to this computer (Vault)."""
        url = str(payload.get("url", ""))
        if not url.lower().startswith(("https://", "http://localhost/", "http://127.0.0.1/")):
            raise ValueError("Only https links can be opened.")
        webbrowser.open(url)
        return {}

    def get_publish_model_key(_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Cheap check of which design is open, so the panel reloads only on a change."""
        model_id, time = model_ref()
        return {"key": f"{model_id}|{time}" if model_id else ""}

    bridge.register("load_publish_section", sections.request)
    bridge.register("load_publish_section_status", sections.status)
    bridge.register("get_publish_model_key", get_publish_model_key)
    bridge.register("open_url", open_url)

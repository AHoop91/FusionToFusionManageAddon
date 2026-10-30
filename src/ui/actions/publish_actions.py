"""Palette actions for the Publish Item panel: loading the open design's sections, opening links, and saying which design is open.

The sections and how each is loaded are in ``publish.panel_sections``.
"""

import webbrowser
from typing import Any, Callable, Dict, Tuple

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...core.logging_setup import get_logger
from ...config.hub_context import capture_context
from ...publish.panel_sections import PublishSections
from ..message_bridge import MessageBridge
from .design_ref import model_ref

log = get_logger("publish_actions")

# What a link opened from the panel may start with: https, or http to this computer (Vault's own pages).
OPENABLE_PREFIXES = ("https://", "http://localhost/", "http://127.0.0.1/")


def is_openable(url: str) -> bool:
    """Whether the add-in may open ``url`` in the system browser: a link of the kinds in ``OPENABLE_PREFIXES``, without any space or control
    character (a link comes from the panel, and from Fusion Manage's own data shown in it, so it is not trusted)."""
    return url.lower().startswith(OPENABLE_PREFIXES) and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)


def model_key(model_id: str, time: str) -> str:
    """What the panel compares to tell whether another design, or another version of it, is open ("" when none is saved)."""
    return f"{model_id}|{time}" if model_id else ""


def current_stamp(config: ConfigService) -> str:
    """The stamp of the hub and settings now active ("" when they cannot be read, which differs from every stamp a read was made under, so
    the panel reads again and shows why)."""
    try:
        return capture_context(config).stamp
    except Exception:  # noqa: BLE001 - Shared Configuration that cannot be read: the load that follows says so
        log.debug("Could not take the stamp of the settings", exc_info=True)
        return ""


def register_publish_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                             open_model_ref: Callable[[], Tuple[str, str]] = model_ref,
                             open_browser: Callable[[str], bool] = webbrowser.open) -> None:
    """Register the section load handlers, ``get_publish_model_key`` and ``open_url``.

    Queries run on worker threads and the panel asks for the answer, so Fusion's UI thread is never blocked. Loaded sections are kept for
    the open design, so switching back to a tab does not query again. ``open_model_ref`` gives ``(model id, timestamp)`` of the open design
    and ``open_browser`` opens a link; both are Fusion's and the system's, so a test gives its own.
    """
    sections = PublishSections(config, auth, open_model_ref)

    def open_url(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open a link in the system browser (a palette cannot open one itself)."""
        url = str(payload.get("url", ""))
        if not is_openable(url):
            raise ValueError("Only https links can be opened.")
        if not open_browser(url):
            log.warning("The system browser did not open %s", url.split("?", 1)[0])   # without the query: it may carry a token
        return {}

    def get_publish_model_key(_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Cheap check of which design is open, and under which settings, so the panel reloads only on a change."""
        return {"key": model_key(*open_model_ref()), "stamp": current_stamp(config)}

    bridge.register("load_publish_section", sections.request)
    bridge.register("load_publish_section_status", sections.status)
    bridge.register("get_publish_model_key", get_publish_model_key)
    bridge.register("open_url", open_url)

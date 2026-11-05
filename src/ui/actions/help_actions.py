"""Palette action for the Help button of every panel: open the documentation in the system browser, in the language in use when it has one."""

import webbrowser
from typing import Any, Callable, Dict

from ...core import i18n
from ...core.logging_setup import get_logger
from ..message_bridge import MessageBridge

log = get_logger("help_actions")

DOCS_URL = "https://ahoop91.github.io/FusionToFusionManageAddon/"

# The languages the documentation is translated into (a folder of that name on the site). The documentation is in English until a language
# is listed here, so a language that is not listed opens the English pages.
DOCS_LANGUAGES = frozenset()


def help_url(code: str) -> str:
    """The address of the documentation for the language ``code``: its own pages when it has them, the English ones otherwise."""
    matched = next((known for known in DOCS_LANGUAGES if known.lower() == (code or "").lower()), None)
    return f"{DOCS_URL}{matched}/" if matched else DOCS_URL


def register_help_actions(bridge: MessageBridge, open_browser: Callable[[str], bool] = webbrowser.open) -> None:
    """Register ``open_help``. ``open_browser`` opens a link and is the system's, so a test gives its own."""
    def open_help(_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not open_browser(help_url(i18n.active_code())):
            log.warning("The system browser did not open the documentation")
        return {}

    bridge.register("open_help", open_help)

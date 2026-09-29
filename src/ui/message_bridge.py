"""Typed message bridge between the HTML palette (JS) and Python.

JS sends ``adsk.fusionSendData(action, jsonString)``; Python replies with
``palette.sendInfoToHTML(action, jsonString)``. Actions are registered here
so each one has a single, testable handler and unknown actions are rejected
instead of silently ignored.
"""

import json
from typing import Any, Callable, Dict

from ..core.logging_setup import get_logger

log = get_logger("bridge")

Handler = Callable[[Dict[str, Any]], Any]


class MessageBridge:
    """Routes named actions from the palette to registered handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}

    def register(self, action: str, handler: Handler) -> None:
        """Register ``handler`` for ``action``. Re-registering is an error."""
        if action in self._handlers:
            raise ValueError(f"Action already registered: {action}")
        self._handlers[action] = handler

    def dispatch(self, action: str, raw_data: str) -> Dict[str, Any]:
        """Run the handler for ``action`` and return a response envelope.

        The envelope is ``{"ok": bool, "result": ..., "error": str|None}`` so
        the UI can handle failures uniformly. Handler exceptions are caught and
        logged; they never propagate into Fusion's event loop.
        """
        handler = self._handlers.get(action)
        if handler is None:
            log.warning("Unknown action: %s", action)
            return {"ok": False, "result": None, "error": f"Unknown action: {action}"}
        try:
            payload = json.loads(raw_data) if raw_data else {}
            return {"ok": True, "result": handler(payload), "error": None}
        except Exception as exc:  # noqa: BLE001 - boundary to UI, must not raise
            log.exception("Action failed: %s", action)
            return {"ok": False, "result": None, "error": str(exc)}

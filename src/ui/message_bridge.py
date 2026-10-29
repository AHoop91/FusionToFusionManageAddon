"""Typed message bridge between the HTML palette (JS) and Python.

JS sends ``adsk.fusionSendData(action, jsonString)``; Python replies with
``palette.sendInfoToHTML(action, jsonString)``. Actions are registered here
so each one has a single, testable handler and unknown actions are rejected
instead of silently ignored.
"""

import json
from typing import Any, Callable, Dict, Optional

from ..core.logging_setup import get_logger

log = get_logger("bridge")

Handler = Callable[[Dict[str, Any]], Any]
Pusher = Callable[[str, str], None]   # (action, JSON text): sends to the open panels, from any thread


class MessageBridge:
    """Routes named actions from the palette to registered handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}
        self._pusher: Optional[Pusher] = None

    def set_pusher(self, pusher: Optional[Pusher]) -> None:
        """Say how to reach the panels from a worker thread (``None`` when there is no way: at start-up and at shutdown)."""
        self._pusher = pusher

    def push(self, action: str, result: Any, ok: bool = True, error: Optional[str] = None) -> None:
        """Tell the panels the outcome of background work, on the action name they asked it under, in the same envelope as a reply.

        Safe from any thread. Without a pusher, or when it fails, nothing is sent: the panel gives up on its own after a while.
        """
        pusher = self._pusher
        if pusher is None:
            return
        try:
            pusher(action, json.dumps({"ok": ok, "result": result, "error": error}))
            log.debug("Pushed %s", action)
        except Exception:  # noqa: BLE001 - background work must never fail because a panel could not be told
            log.exception("Could not push %s", action)

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
            if not isinstance(payload, dict):   # every handler reads its payload as an object
                raise ValueError("The request must be a JSON object.")
            return {"ok": True, "result": handler(payload), "error": None}
        except Exception as exc:  # noqa: BLE001 - boundary to UI, must not raise
            log.exception("Action failed: %s", action)
            return {"ok": False, "result": None, "error": str(exc)}

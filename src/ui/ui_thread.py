"""Run work on Fusion's main thread from outside a palette message handler.

A palette handler blocks the palette's own message loop while it runs, which is a poor place for
slow Fusion work such as opening documents. A custom event runs its handler on the main thread
after the palette handler has returned, so the panel stays able to poll and cancel between tasks.
"""

import queue
from typing import Callable

import adsk.core

from ..core.logging_setup import get_logger

log = get_logger("ui_thread")

EVENT_ID = "MfgToFm_UiTask"


class _Handler(adsk.core.CustomEventHandler):
    def __init__(self, tasks: "queue.Queue") -> None:
        super().__init__()
        self._tasks = tasks

    def notify(self, args) -> None:
        try:
            task = self._tasks.get_nowait()
        except queue.Empty:
            return
        try:
            task()
        except Exception:  # a task must never raise into Fusion
            log.exception("A main-thread task failed")


class UiThread:
    """``post(task)`` runs ``task()`` later on the main thread, one task per call, in order."""

    def __init__(self) -> None:
        self._app = adsk.core.Application.get()
        self._tasks: "queue.Queue" = queue.Queue()
        try:
            self._app.unregisterCustomEvent(EVENT_ID)   # left over from a previous run of the add-in
        except RuntimeError:
            pass
        self._event = self._app.registerCustomEvent(EVENT_ID)
        self._handler = _Handler(self._tasks)   # kept, or Fusion drops the handler
        self._event.add(self._handler)

    def post(self, task: Callable[[], None]) -> None:
        self._tasks.put(task)
        self._app.fireCustomEvent(EVENT_ID, "")

    def dispose(self) -> None:
        try:
            self._event.remove(self._handler)
            self._app.unregisterCustomEvent(EVENT_ID)
        except RuntimeError:
            pass

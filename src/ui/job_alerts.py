"""A message box when a publish ends, whether or not the Publish and Job Queue panels are open.

``UserInterface.messageBox`` is Fusion's own popup, so nothing else is added to the screen. It is
modal: it waits for OK. ``alert`` and ``done`` may be called from any thread;
the box is shown later on Fusion's main thread.
"""

import adsk.core

from ..core.logging_setup import get_logger
from .ui_thread import UiThread

log = get_logger("job_alerts")

FAILED_TITLE = "Publish failed"
DONE_TITLE = "Publish complete"


class JobAlerts:
    """``alert(message)`` shows a warning box, ``done(message)`` an information box; both have an OK button."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread) -> None:
        self._ui = ui
        self._tasks = tasks

    def alert(self, message: str, title: str = FAILED_TITLE) -> None:
        self._tasks.post(lambda: self._show(message, title, adsk.core.MessageBoxIconTypes.WarningIconType))

    def done(self, message: str, title: str = DONE_TITLE) -> None:
        self._tasks.post(lambda: self._show(message, title, adsk.core.MessageBoxIconTypes.InformationIconType))

    def _show(self, message: str, title: str, icon) -> None:
        try:
            self._ui.messageBox(message, title, adsk.core.MessageBoxButtonTypes.OKButtonType, icon)
        except Exception:  # an alert must never break a publish
            log.exception("Could not show the alert")

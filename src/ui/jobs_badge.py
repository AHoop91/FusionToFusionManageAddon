"""The Job Queue button on the ribbon shows what the queue is doing.

Fusion has no badge for a ribbon button, so the button's icon is swapped for a copy with a coloured
dot: green while publishes are waiting or running (``resources/jobs_running``), red while one has
failed (``resources/jobs_error``), the plain icon otherwise (``resources/jobs``). The tooltip says
the same. ``update`` may be called from any thread: the command definition is only touched on
Fusion's main thread.
"""

import os
from typing import Dict, Tuple

import adsk.core

from ..core.logging_setup import get_logger
from ..publish.job_queue import FAILED, IDLE, WORKING
from .ui_thread import UiThread

log = get_logger("jobs_badge")

# state -> (icon folder under resources, what the tooltip adds)
LOOKS: Dict[str, Tuple[str, str]] = {
    IDLE: ("jobs", ""),
    WORKING: ("jobs_running", " A publish is running."),
    FAILED: ("jobs_error", " A publish failed: see the list."),
}


class JobsBadge:
    """Switches the icon and tooltip of one ribbon command between the looks of the queue's states."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, command_id: str, tooltip: str,
                 resources_dir: str) -> None:
        self._ui = ui
        self._tasks = tasks
        self._command_id = command_id
        self._tooltip = tooltip
        self._resources = resources_dir
        self._state = IDLE

    def update(self, state: str) -> None:
        """Show the look of ``state`` (``IDLE``, ``WORKING`` or ``FAILED`` of the queue); safe from any thread."""
        if state in LOOKS:
            self._tasks.post(lambda: self._apply(state))

    def _apply(self, state: str) -> None:
        if state == self._state:
            return
        try:
            definition = self._ui.commandDefinitions.itemById(self._command_id)
            if definition is None:
                return
            folder, note = LOOKS[state]
            definition.resourceFolder = os.path.join(self._resources, folder)
            definition.tooltip = self._tooltip + note
            self._state = state
        except Exception:  # an icon must never break a publish
            log.exception("Could not update the Job Queue button")

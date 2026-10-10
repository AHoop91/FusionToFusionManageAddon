"""Switches commands off while what they need is not ready.

A ``RibbonCommand`` with ``needs_setup`` is enabled only when the settings are complete; one with ``needs_drawing`` only when, as well,
the open drawing has loaded enough to say which item it is of. Disabling the command definition greys out every control made from
it, in the ribbon and in the right-click menu alike, and the tooltip says why. The reasons are put together here, in one place,
so one cannot undo the other.
"""

import threading
from typing import Callable, Dict, Sequence

import adsk.core

from ..core.logging_setup import get_logger
from .ribbon import RibbonCommand
from .ui_thread import UiThread

log = get_logger("availability")


class SetupGate:
    """Enables or disables the commands that need the settings to be complete, and a loaded drawing."""

    def __init__(self, ui: adsk.core.UserInterface, commands: Sequence[RibbonCommand], problem: Callable[[], str],
                 drawing_problem: Callable[[], str] = lambda: "") -> None:
        self._ui = ui
        self._commands = [c for c in commands if c.needs_setup or c.needs_drawing]
        self._problem = problem
        self._drawing_problem = drawing_problem
        self._shown: Dict[str, str] = {}   # command id -> the reason last applied, so only a change is written

    def refresh(self) -> None:
        """Apply the present state of the settings and of the open drawing. Call it after either may have changed. Main thread."""
        try:
            setup = self._problem()
            drawing = self._drawing_problem()
        except Exception:  # noqa: BLE001 - unknown state: leave the commands as they are
            log.exception("Could not check what the commands need")
            return
        for command in self._commands:
            reason = (setup if command.needs_setup else "") or (drawing if command.needs_drawing else "")
            if self._shown.get(command.command_id) == reason:
                continue
            definition = self._ui.commandDefinitions.itemById(command.command_id)
            if definition is None:
                continue
            definition.controlDefinition.isEnabled = not reason
            definition.tooltip = command.tooltip if not reason else f"{command.tooltip}\nNot available: {reason}"
            self._shown[command.command_id] = reason
            log.info("%s is %s%s", command.name, "disabled: " if reason else "enabled", reason)


class GateWatcher:
    """Asks the gate to look again every few seconds, on the main thread: a drawing loads, and a document is switched, without any
    event of ours to say so."""

    def __init__(self, tasks: UiThread, gate: SetupGate, seconds: float = 2.0) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(tasks, gate, seconds), daemon=True)
        self._thread.start()

    def _run(self, tasks: UiThread, gate: SetupGate, seconds: float) -> None:
        while not self._stop.wait(seconds):
            tasks.post(gate.refresh)

    def dispose(self) -> None:
        self._stop.set()

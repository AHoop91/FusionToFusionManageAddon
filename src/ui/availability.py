"""Switches commands off while what they need is not ready.

A ``RibbonCommand`` with ``needs_setup`` is enabled only when the settings are complete; one with ``needs_drawing`` only when, as well,
the open drawing has loaded enough to say which item it is of. Disabling the command definition greys out every control made from
it, in the ribbon and in the right-click menu alike, and the tooltip says why. The reasons are put together here, in one place,
so one cannot undo the other.
"""

import threading
import time
from typing import Callable, Dict, Optional, Sequence

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


class _DocumentHandler(adsk.core.DocumentEventHandler):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callback = callback

    def notify(self, args) -> None:
        self._callback()


class _DataReadyHandler(adsk.core.MFGDMDataEventHandler):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callback = callback

    def notify(self, args) -> None:
        self._callback()


class _WorkspaceHandler(adsk.core.WorkspaceEventHandler):
    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callback = callback

    def notify(self, args) -> None:
        self._callback()


class GateWatcher:
    """Asks the gate to look again when a document is opened or activated, a workspace is entered, or Fusion reports a document's
    data model properties ready (``mfgdmDataReady``): Fusion's events, on the main thread. Should a drawing still not be ready after
    them, it is looked at again every ``seconds``, for at most ``give_up`` seconds; nothing runs when no drawing is loading."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, gate: SetupGate, loading: Callable[[], bool],
                 seconds: float = 2.0, give_up: float = 60.0, grace: float = 15.0,
                 on_event: Optional[Callable[[], None]] = None) -> None:
        self._app = adsk.core.Application.get()
        self._on_event = on_event   # also run on each check (the active hub can change with the document)
        self._ui = ui
        self._tasks = tasks
        self._gate = gate
        self._loading = loading   # True while the open document is a drawing that is not ready yet
        self._seconds = seconds
        self._give_up = give_up
        self._stop = threading.Event()
        self._polling = False
        self._deadline = 0.0
        self._grace = grace   # how long after the last event the poll waits before it steps in
        self._quiet_until = 0.0
        self._document_handler = _DocumentHandler(self.check)   # kept, or Fusion drops the handlers
        self._workspace_handler = _WorkspaceHandler(self.check)
        self._data_handler = _DataReadyHandler(self.check)   # Fusion says the document's data model properties are ready
        self._app.mfgdmDataReady.add(self._data_handler)
        self._app.documentActivated.add(self._document_handler)
        self._app.documentOpened.add(self._document_handler)
        self._ui.workspaceActivated.add(self._workspace_handler)

    def check(self, polled: bool = False) -> None:
        """Refresh the gate now, and keep watching if a drawing is still loading. Main thread.

        ``polled`` is True when the fallback poll asked, False when a Fusion event did; an event holds the poll off for ``grace``."""
        try:
            if self._on_event:
                self._on_event()
            self._gate.refresh()
            waiting = self._loading()
        except Exception:  # noqa: BLE001 - never raise into Fusion
            log.exception("Could not check what the commands need")
            waiting = True   # unknown state: look again shortly, within the give-up time
        if not waiting:
            if self._polling:
                log.info("Drawing ready (%s)", "found by the fallback poll" if polled else "on a Fusion event")
            self._polling = False
            return
        now = time.monotonic()
        if not polled:
            self._quiet_until = now + self._grace
            self._deadline = now + self._give_up
        if not self._polling and not self._stop.is_set():
            self._polling = True
            threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self) -> None:
        """The fallback: only once no event has come for ``grace`` seconds, look again every ``seconds``."""
        while self._polling and not self._stop.wait(self._seconds):
            now = time.monotonic()
            if now > self._deadline:
                break
            if now >= self._quiet_until:
                self._tasks.post(lambda: self.check(True))
        self._polling = False

    def dispose(self) -> None:
        self._stop.set()
        self._polling = False
        for event, handler in ((self._app.mfgdmDataReady, self._data_handler),
                               (self._app.documentActivated, self._document_handler),
                               (self._app.documentOpened, self._document_handler),
                               (self._ui.workspaceActivated, self._workspace_handler)):
            try:
                event.remove(handler)
            except RuntimeError:
                pass

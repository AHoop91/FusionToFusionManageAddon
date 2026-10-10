"""Switches commands off while the settings they need are not complete.

A ``RibbonCommand`` with ``needs_setup`` is enabled only when ``problem()`` gives no reason. Disabling the command
definition greys out every control made from it, in the ribbon and in the right-click menu alike, and the tooltip says why.
"""

from typing import Callable, Sequence

import adsk.core

from ..core.logging_setup import get_logger
from .ribbon import RibbonCommand

log = get_logger("availability")


class SetupGate:
    """Enables or disables the commands that need the settings to be complete."""

    def __init__(self, ui: adsk.core.UserInterface, commands: Sequence[RibbonCommand], problem: Callable[[], str]) -> None:
        self._ui = ui
        self._commands = [c for c in commands if c.needs_setup]
        self._problem = problem

    def refresh(self) -> None:
        """Apply the present state of the settings. Call it after they change. Main thread."""
        try:
            reason = self._problem()
        except Exception:  # noqa: BLE001 - unknown state: leave the commands as they are
            log.exception("Could not check the settings")
            return
        for command in self._commands:
            definition = self._ui.commandDefinitions.itemById(command.command_id)
            if definition is None:
                continue
            definition.controlDefinition.isEnabled = not reason
            definition.tooltip = command.tooltip if not reason else f"{command.tooltip}\nNot available: {reason}"
        log.info("Commands that need the settings are %s%s", "disabled: " if reason else "enabled", reason)

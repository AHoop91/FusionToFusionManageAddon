"""The add-in's entries in Fusion's right-click menu.

This decides which of the add-in's commands are offered for the selected entities, in a design or in a drawing, and registers and removes
those entries. Choosing an entry runs the command the add-in gave it; what the entry does is not decided here.

Layer: UI (event wiring for a Fusion menu). The selection it saw is kept in ``fusion_selection.menu_selection``.
"""

from typing import Any, List, Optional, Sequence

import adsk.core

from ..core.logging_setup import get_logger
from . import drawing_source, fusion_selection
from .ribbon import RibbonCommand, define_command

log = get_logger("item_context_menu")

LINE_ID = "MfgToFm_MenuLine"   # the line above the add-in's entries in the right-click menu


def _menu_context(entities: Sequence[Any]) -> Optional[str]:
    """The kind of document the right-click menu is offered in for the selected ``entities`` ("drawing" for any selection, "design" for a
    selected component), or None when it is not offered."""
    if drawing_source.active_drawing() is not None:
        return "drawing" if entities else None
    return "design" if any(fusion_selection.component_of(e) is not None for e in entities) else None


def _is_offered(command: RibbonCommand, context: str, is_root: bool) -> bool:
    """Whether ``command`` is offered in a ``context`` document, given whether the top of the tree is selected."""
    in_context = not command.context or command.context == context
    return in_context and (is_root or not command.root_only)


def _update_menu_entry(controls: Any, definitions: Any, command: RibbonCommand, offered: bool) -> None:
    """Add ``command`` to the menu ``controls`` when ``offered`` (once), else remove it if an earlier opening of the menu left it there."""
    shown = controls.itemById(command.command_id)
    if not offered:
        if shown is not None:
            shown.deleteMe()
        return
    definition = definitions.itemById(command.command_id)
    if definition and shown is None:
        controls.addCommand(definition)


def _fill_menu(event: adsk.core.MarkingMenuEventArgs, commands: Sequence[RibbonCommand]) -> None:
    """Add ``commands`` to the right-click menu of ``event`` under one line, those that suit what is selected. UI thread."""
    entities = list(event.selectedEntities)
    fusion_selection.menu_selection[:] = entities
    context = _menu_context(entities)
    if context is None:
        return
    definitions = adsk.core.Application.get().userInterface.commandDefinitions
    controls = event.linearMarkingMenu.controls
    is_root = drawing_source.selects_top_level(entities) if context == "drawing" else fusion_selection.selects_root(entities)
    if controls.itemById(LINE_ID) is None and controls.itemById(commands[0].command_id) is None:
        controls.addSeparator(LINE_ID)   # one line above the group, none between its entries
    for command in commands:
        _update_menu_entry(controls, definitions, command, _is_offered(command, context, is_root))


class _MenuHandler(adsk.core.MarkingMenuEventHandler):
    """Adds the commands to the right-click menu when something is selected, under one line.

    In a design the menu appears for a selected component; in a drawing, for any selection. A command with a ``context`` is offered
    only in that kind of document, and one marked ``root_only`` only when the top of the tree is selected.
    """

    def __init__(self, commands: Sequence[RibbonCommand]) -> None:
        super().__init__()
        self._commands = list(commands)

    def notify(self, args) -> None:
        try:
            _fill_menu(adsk.core.MarkingMenuEventArgs.cast(args), self._commands)
        except Exception:  # noqa: BLE001 - boundary to Fusion, must not raise
            log.exception("Could not add the Fusion Manage menu entries")


class ItemContextMenu:
    """Registers the right-click entries; each runs its own command, under one line."""

    def __init__(self, ui: adsk.core.UserInterface, commands: Sequence[RibbonCommand]) -> None:
        self._ui = ui
        self._commands = list(commands)
        self._handlers: List[object] = []   # kept, or Fusion drops them
        for command in self._commands:
            define_command(ui, command, self._handlers)
        self._handler = _MenuHandler(self._commands)
        ui.markingMenuDisplaying.add(self._handler)

    def dispose(self) -> None:
        try:
            self._ui.markingMenuDisplaying.remove(self._handler)
        except RuntimeError:
            pass
        for command in self._commands:
            definition = self._ui.commandDefinitions.itemById(command.command_id)
            if definition:
                definition.deleteMe()
        self._handlers.clear()

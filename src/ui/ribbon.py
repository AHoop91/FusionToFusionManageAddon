"""Native Fusion ribbon: an add-in tab with panels of command buttons.

The tab is created in each configured workspace, with the panels given for it. Buttons are declared as
``RibbonCommand`` values grouped in ``RibbonPanel`` values, so adding a
command or panel is one entry in the lists passed to ``Ribbon``; no Fusion
plumbing changes.

Fusion creates a new command instance on every click and raises
``commandCreated``; the ``execute`` handler is attached to that instance.
Handlers must be kept referenced for the add-in lifetime or Fusion
garbage-collects them and the button silently stops working.
"""

import traceback
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

import adsk.core

from ..core.constants import RIBBON_TAB_ID, RIBBON_TAB_NAME
from ..core.logging_setup import get_logger

log = get_logger("ribbon")


@dataclass(frozen=True)
class RibbonCommand:
    """One ribbon button.

    ``resource_folder`` holds the icons (``16x16.png``, ``32x32.png``); leave
    it empty to use Fusion's default icon.
    """

    command_id: str
    name: str
    tooltip: str
    on_click: Callable[[], None]
    resource_folder: str = ""
    promoted: bool = True   # a button on the panel; False puts it in the panel's dropdown
    needs_setup: bool = False   # greyed out until the settings are complete (see ``SetupGate``)
    root_only: bool = False   # a right-click entry offered only when the top of the tree is selected (a design's root, the top of what a drawing shows)
    needs_drawing: bool = False   # greyed out until the open drawing has loaded enough to say which item it is of (see ``SetupGate``)
    context: str = ""   # a right-click entry offered only in "design" or "drawing" documents; "" in either


class _ExecuteHandler(adsk.core.CommandEventHandler):
    """Runs a button's action when its command executes."""

    def __init__(self, ui: adsk.core.UserInterface, command: RibbonCommand) -> None:
        super().__init__()
        self._ui = ui
        self._command = command

    def notify(self, args) -> None:
        try:
            log.info("Command executed: %s", self._command.command_id)
            self._command.on_click()
        except Exception:  # noqa: BLE001 - boundary to Fusion, must not raise
            log.exception("Ribbon action failed: %s", self._command.command_id)
            self._ui.messageBox(f"{self._command.name} failed:\n{traceback.format_exc()}")


class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    """Attaches an execute handler to each newly created command instance."""

    def __init__(self, ui: adsk.core.UserInterface, command: RibbonCommand,
                 keep_alive: List[object]) -> None:
        super().__init__()
        self._ui = ui
        self._command = command
        self._keep_alive = keep_alive

    def notify(self, args) -> None:
        try:
            instance = adsk.core.CommandCreatedEventArgs.cast(args).command
            handler = _ExecuteHandler(self._ui, self._command)
            instance.execute.add(handler)
            self._keep_alive.append(handler)
        except Exception:  # noqa: BLE001 - boundary to Fusion, must not raise
            log.exception("Failed to wire command: %s", self._command.command_id)


def define_command(ui: adsk.core.UserInterface, command: RibbonCommand, handlers: List[object]) -> adsk.core.CommandDefinition:
    """Create (or reuse) the command definition of ``command`` and hook its click; ``handlers`` keeps the handler alive."""
    definition = ui.commandDefinitions.itemById(command.command_id)
    if definition is None:
        definition = ui.commandDefinitions.addButtonDefinition(
            command.command_id, command.name, command.tooltip, command.resource_folder)
    handler = _CreatedHandler(ui, command, handlers)
    definition.commandCreated.add(handler)
    handlers.append(handler)
    return definition


@dataclass(frozen=True)
class RibbonPanel:
    """One panel of buttons on the tab. Panels appear in the order given."""

    panel_id: str
    name: str
    commands: Sequence[RibbonCommand]


class Ribbon:
    """Creates and removes the add-in ribbon tab, with the panels of each workspace (a drawing does not get what a design does)."""

    def __init__(self, ui: adsk.core.UserInterface, panels_by_workspace: Dict[str, Sequence[RibbonPanel]]) -> None:
        self._ui = ui
        self._panels_by_workspace = {workspace_id: list(panels) for workspace_id, panels in panels_by_workspace.items()}
        self._handlers: List[object] = []

    # ---- Ids ---------------------------------------------------------------
    # Tab and panel ids must be unique per workspace, so the workspace id is
    # part of them.

    @staticmethod
    def _tab_id(workspace_id: str) -> str:
        return f"{RIBBON_TAB_ID}_{workspace_id}"

    @staticmethod
    def _panel_id(panel: RibbonPanel, workspace_id: str) -> str:
        return f"{panel.panel_id}_{workspace_id}"

    def commands(self) -> List[RibbonCommand]:
        """Every command of every workspace, each once (one definition serves a button in several workspaces)."""
        found: Dict[str, RibbonCommand] = {}
        for panels in self._panels_by_workspace.values():
            for panel in panels:
                for command in panel.commands:
                    found.setdefault(command.command_id, command)
        return list(found.values())

    # ---- Lifecycle ---------------------------------------------------------

    def register(self) -> None:
        """Create the command definitions, then the tab and panels per workspace."""
        definitions = {command.command_id: self._define(command) for command in self.commands()}
        for workspace_id, panels in self._panels_by_workspace.items():
            workspace = self._ui.workspaces.itemById(workspace_id)
            if workspace is None:
                log.warning("Workspace not found, no ribbon added: %s (Fusion has: %s)", workspace_id,
                            ", ".join(self._ui.workspaces.item(i).id for i in range(self._ui.workspaces.count)))
                continue
            tab = workspace.toolbarTabs.itemById(self._tab_id(workspace_id)) \
                or workspace.toolbarTabs.add(self._tab_id(workspace_id), RIBBON_TAB_NAME)
            for ribbon_panel in panels:
                panel = tab.toolbarPanels.itemById(self._panel_id(ribbon_panel, workspace_id)) \
                    or tab.toolbarPanels.add(self._panel_id(ribbon_panel, workspace_id), ribbon_panel.name)
                for command in ribbon_panel.commands:
                    definition = definitions[command.command_id]
                    control = panel.controls.itemById(definition.id) or panel.controls.addCommand(definition)
                    # Promoted controls show as buttons on the panel; the others go into its dropdown.
                    control.isPromotedByDefault = command.promoted
                    control.isPromoted = command.promoted

    def unregister(self) -> None:
        """Remove tabs, panels and command definitions. Safe to call repeatedly."""
        for workspace_id, panels in self._panels_by_workspace.items():
            workspace = self._ui.workspaces.itemById(workspace_id)
            tab = workspace.toolbarTabs.itemById(self._tab_id(workspace_id)) if workspace else None
            if tab is None:
                continue
            for ribbon_panel in panels:
                panel = tab.toolbarPanels.itemById(self._panel_id(ribbon_panel, workspace_id))
                if panel:
                    panel.deleteMe()
            tab.deleteMe()
        for command in self.commands():
            definition = self._ui.commandDefinitions.itemById(command.command_id)
            if definition:
                definition.deleteMe()
        self._handlers.clear()

    def _define(self, command: RibbonCommand) -> adsk.core.CommandDefinition:
        """Create (or reuse) the command definition and hook its click."""
        return define_command(self._ui, command, self._handlers)

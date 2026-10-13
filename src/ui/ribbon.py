"""Native Fusion ribbon: an add-in tab with panels of command buttons.

The panels go into Fusion's own tab called ``host_tab_name`` ("Manage"); where that tab cannot be found the add-in gets a tab of its
own. A panel is made of groups of buttons, told apart by a separator. Buttons are declared as
``RibbonCommand`` values grouped in ``RibbonGroup`` and ``RibbonPanel`` values, so adding a
command or panel is one entry in the lists passed to ``Ribbon``; no Fusion
plumbing changes.

Fusion creates a new command instance on every click and raises
``commandCreated``; the ``execute`` handler is attached to that instance.
Handlers must be kept referenced for the add-in lifetime or Fusion
garbage-collects them and the button silently stops working.
"""

import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence

import adsk.core

from ..core.constants import RIBBON_TAB_ID, RIBBON_TAB_NAME
from ..core.logging_setup import get_logger

log = get_logger("ribbon")


@dataclass(frozen=True)
class RibbonCommand:
    """One ribbon button.

    ``resource_folder`` holds the icons (``16x16.svg``, ``32x32.svg``); leave
    it empty to use Fusion's default icon.
    """

    command_id: str
    name: str
    tooltip: str
    on_click: Callable[[], None]
    resource_folder: str = ""
    promoted: bool = True   # a button on the ribbon bar; False puts it in the panel's dropdown (or, in a submenu, leaves it there only)
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
class RibbonGroup:
    """Commands of a panel that go together: apart from the others by a separator, and under one name as a submenu if ``submenu_icon`` is set."""

    commands: Sequence[RibbonCommand]
    name: str = ""   # the submenu's name
    submenu_icon: str = ""   # this folder of icons makes the group a submenu; "" for loose buttons


@dataclass(frozen=True)
class RibbonPanel:
    """One panel of the ribbon. Panels appear in the order given."""

    panel_id: str
    name: str
    groups: Sequence[RibbonGroup]

    @property
    def commands(self) -> List[RibbonCommand]:
        return [command for group in self.groups for command in group.commands]


class Ribbon:
    """Creates and removes the add-in's ribbon panels for each workspace (a drawing does not get what a design does).

    The panels are put in Fusion's own tab called ``host_tab_name``; a workspace with no such tab gets a tab of the add-in's own instead.
    """

    def __init__(self, ui: adsk.core.UserInterface, panels_by_workspace: Dict[str, Sequence[RibbonPanel]], host_tab_name: str = "") -> None:
        self._ui = ui
        self._panels_by_workspace = {workspace_id: list(panels) for workspace_id, panels in panels_by_workspace.items()}
        self._host_tab_name = host_tab_name
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

    def _host_tab(self, workspace: Any) -> Any:
        """Fusion's tab called ``host_tab_name`` in ``workspace``, or None (every tab is logged then, to find the right name)."""
        if not self._host_tab_name:
            return None
        tabs = [workspace.toolbarTabs.item(i) for i in range(workspace.toolbarTabs.count)]
        for tab in tabs:
            if tab.name.strip().lower() == self._host_tab_name.lower():
                return tab
        log.warning("No '%s' tab in %s; the add-in gets a tab of its own. The tabs are: %s", self._host_tab_name, workspace.id,
                    ", ".join(f"{t.name} ({t.id})" for t in tabs))
        return None

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
        """Create the command definitions, then the panels per workspace."""
        definitions = {command.command_id: self._define(command) for command in self.commands()}
        for workspace_id, panels in self._panels_by_workspace.items():
            workspace = self._ui.workspaces.itemById(workspace_id)
            if workspace is None:
                log.warning("Workspace not found, no ribbon added: %s (Fusion has: %s)", workspace_id,
                            ", ".join(self._ui.workspaces.item(i).id for i in range(self._ui.workspaces.count)))
                continue
            tab = self._host_tab(workspace) or workspace.toolbarTabs.itemById(self._tab_id(workspace_id)) \
                or workspace.toolbarTabs.add(self._tab_id(workspace_id), RIBBON_TAB_NAME)
            for ribbon_panel in panels:
                panel_id = self._panel_id(ribbon_panel, workspace_id)
                panel = tab.toolbarPanels.itemById(panel_id) or tab.toolbarPanels.add(panel_id, ribbon_panel.name)
                self._add_groups(panel, panel_id, ribbon_panel, definitions)

    def _add_groups(self, panel: Any, panel_id: str, ribbon_panel: RibbonPanel, definitions: Dict[str, Any]) -> None:
        """The groups of ``ribbon_panel`` in ``panel``, a separator between them."""
        for number, group in enumerate(ribbon_panel.groups):
            if number:
                separator_id = f"{panel_id}_separator{number}"
                if panel.controls.itemById(separator_id) is None:
                    panel.controls.addSeparator(separator_id)
            if not group.submenu_icon:
                self._add_controls(panel, group.commands, definitions)
                continue
            # Fusion has no heading control, so a group with a submenu names it that way. Its commands are in the submenu, the promoted
            # ones pinned from there: a button added to the panel as well would be listed twice in its dropdown.
            try:
                self._add_submenu(panel, f"{panel_id}_submenu{number}", group, definitions)
            except Exception:  # noqa: BLE001 - the other groups are still added
                log.exception("Could not add the '%s' submenu", group.name)

    @staticmethod
    def _add_submenu(panel: Any, submenu_id: str, group: RibbonGroup, definitions: Dict[str, Any]) -> None:
        """A submenu of the panel named for ``group``, with its commands."""
        submenu = panel.controls.itemById(submenu_id) or panel.controls.addDropDown(group.name, group.submenu_icon, submenu_id)
        for command in group.commands:
            definition = definitions[command.command_id]
            control = submenu.controls.itemById(definition.id) or submenu.controls.addCommand(definition)
            if command.promoted:   # pinned to the ribbon bar, as "Pin to Toolbar" does; the dropdown of the panel lists the submenu only
                pinned = adsk.core.CommandControl.cast(control).promote(True)
                log.info("Pinned '%s' of the '%s' submenu to the panel: %s", command.name, group.name, pinned)
        log.info("Added the '%s' submenu with %d command(s)", group.name, submenu.controls.count)

    @staticmethod
    def _add_controls(panel: Any, commands: Sequence[RibbonCommand], definitions: Dict[str, Any]) -> None:
        for command in commands:
            definition = definitions[command.command_id]
            control = panel.controls.itemById(definition.id) or panel.controls.addCommand(definition)
            # Promoted controls show as buttons on the panel; the others go into its dropdown.
            control.isPromotedByDefault = command.promoted
            control.isPromoted = command.promoted

    def unregister(self) -> None:
        """Remove panels, the add-in's own tabs and command definitions. Safe to call repeatedly."""
        for workspace_id, panels in self._panels_by_workspace.items():
            workspace = self._ui.workspaces.itemById(workspace_id)
            if workspace is None:
                continue
            own = workspace.toolbarTabs.itemById(self._tab_id(workspace_id))
            for tab in [self._host_tab(workspace), own]:
                for ribbon_panel in panels if tab is not None else []:
                    panel = tab.toolbarPanels.itemById(self._panel_id(ribbon_panel, workspace_id))
                    if panel:
                        panel.deleteMe()
            if own is not None:
                own.deleteMe()
        for command in self.commands():
            definition = self._ui.commandDefinitions.itemById(command.command_id)
            if definition:
                definition.deleteMe()
        self._handlers.clear()

    def _define(self, command: RibbonCommand) -> adsk.core.CommandDefinition:
        """Create (or reuse) the command definition and hook its click."""
        return define_command(self._ui, command, self._handlers)

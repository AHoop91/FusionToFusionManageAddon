"""Fusion add-in entry point: Manufacturing Data Model to Fusion Manage.

Fusion calls ``run`` when the add-in starts and ``stop`` when it is unloaded.
This module only composes the pieces (config, auth, bridge, palette, toolbar
button); all logic lives in the ``src`` package.
"""

import os
import sys
import traceback

import adsk.core

# ---- Import setup -----------------------------------------------------------
# Make the ``src`` package importable when Fusion loads this file directly.
_ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ADDIN_DIR)

# Fusion keeps imported modules cached across add-in stop/run, so edited files
# would otherwise keep running their old code. Purge ours before importing.
for _name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[_name]

from src.auth.auth_service import AuthService  # noqa: E402
from src.config.config_service import ConfigService  # noqa: E402
from src.config.hub import HubTenant  # noqa: E402
from src.core.logging_setup import get_logger, shutdown_logging  # noqa: E402
from src.ui import drawing_source  # noqa: E402
from src.ui.actions import register_actions  # noqa: E402
from src.ui.availability import GateWatcher, SetupGate  # noqa: E402
from src.ui.export_dialog import ExportDialog  # noqa: E402
from src.ui.file_dialogs import FileDialogs  # noqa: E402
from src.ui.message_bridge import MessageBridge  # noqa: E402
from src.ui.job_alerts import JobAlerts  # noqa: E402
from src.ui.item_panel import ItemContextMenu, ItemPanel  # noqa: E402
from src.ui.jobs_badge import JobsBadge  # noqa: E402
from src.ui.palette_host import PaletteHost  # noqa: E402
from src.ui.ui_thread import UiThread  # noqa: E402
from src.core.constants import (  # noqa: E402
    COMMAND_ID,
    EXPORT_COMMAND_ID,
    EXPORT_HEIGHT,
    EXPORT_PALETTE_ID,
    EXPORT_TITLE,
    EXPORT_WIDTH,
    ITEM_COMMAND_ID,
    ITEM_HEIGHT,
    ITEM_PALETTE_ID,
    ITEM_TITLE,
    ITEM_WIDTH,
    JOBS_COMMAND_ID,
    JOBS_HEIGHT,
    JOBS_PALETTE_ID,
    JOBS_TITLE,
    JOBS_WIDTH,
    MENU_OPEN_COMMAND_ID,
    MENU_PUBLISH_COMMAND_ID,
    MENU_UPLOAD_DRAWING_COMMAND_ID,
    MENU_UPLOAD_STEP_COMMAND_ID,
    PUBLISH_COMMAND_ID,
    PUBLISH_HEIGHT,
    PUBLISH_PALETTE_ID,
    PUBLISH_TITLE,
    PUBLISH_WIDTH,
    RIBBON_ADMINISTRATION_NAME,
    RIBBON_DESIGN_WORKSPACE,
    RIBBON_DRAWING_WORKSPACE,
    RIBBON_EXPORT_PANEL_ID,
    RIBBON_EXPORT_PANEL_NAME,
    RIBBON_HOST_TAB_NAME,
    RIBBON_MERGED_PANEL_ID,
    RIBBON_MERGED_PANEL_NAME,
    SETTINGS_PALETTE_ID,
    SETTINGS_TITLE,
    UPLOAD_PROGRESS_HEIGHT,
    UPLOAD_PROGRESS_PALETTE_ID,
    UPLOAD_PROGRESS_WIDTH,
)
from src.ui.ribbon import Ribbon, RibbonCommand, RibbonGroup, RibbonPanel  # noqa: E402

log = get_logger()

JOBS_TOOLTIP = "Show the job queue: publishes that are waiting, running and finished."
PUBLISH_TOOLTIP = "Preview what will be published to Fusion Manage for the current item."
UPLOAD_DRAWING_NAME = "Export PDF"
UPLOAD_DRAWING_TOOLTIP = "Create a PDF of the open drawing and attach it to the Fusion Manage item of the design it shows."


def _icon(folder: str) -> str:
    """The folder of the icons (``16x16.svg``...) named ``folder`` under ``resources``."""
    return os.path.join(_ADDIN_DIR, "resources", folder)


# ---- Add-in state -----------------------------------------------------------
# Module-level references keep objects (and their Fusion handlers) alive for
# the add-in lifetime.
_ui = None
_palette_host = None
_publish_host = None
_jobs_host = None
_progress_host = None
_export_host = None
_export_dialog = None
_item_host = None
_item_panel = None
_item_menu = None
_ribbon = None
_tasks = None
_gate = None
_watcher = None


# ---- Fusion lifecycle -------------------------------------------------------

def run(context) -> None:
    """Add-in start: compose services, palette and ribbon."""
    global _ui, _palette_host, _publish_host, _jobs_host, _progress_host, _export_host, _export_dialog, _item_host, _item_panel, _item_menu, _ribbon, _tasks, _gate, _watcher
    try:
        _ui = adsk.core.Application.get().userInterface

        bridge = MessageBridge()
        _tasks = UiThread()
        badge = JobsBadge(_ui, _tasks, JOBS_COMMAND_ID, JOBS_TOOLTIP, os.path.join(_ADDIN_DIR, "resources"))
        hub = HubTenant()
        hub.refresh()
        config, auth = ConfigService(tenant=hub.current), AuthService()
        register_actions(bridge, config, auth, FileDialogs(_ui), badge, JobAlerts(_ui, _tasks))

        _palette_host = PaletteHost(_ui, bridge, SETTINGS_PALETTE_ID, SETTINGS_TITLE, "settings")
        _publish_host = PaletteHost(_ui, bridge, PUBLISH_PALETTE_ID, PUBLISH_TITLE, "publish", False, PUBLISH_WIDTH, PUBLISH_HEIGHT)
        _jobs_host = PaletteHost(_ui, bridge, JOBS_PALETTE_ID, JOBS_TITLE, "jobs", False, JOBS_WIDTH, JOBS_HEIGHT)
        _item_host = PaletteHost(_ui, bridge, ITEM_PALETTE_ID, ITEM_TITLE, "item", True, ITEM_WIDTH, ITEM_HEIGHT)
        _progress_host = PaletteHost(_ui, bridge, UPLOAD_PROGRESS_PALETTE_ID, "Upload", "progress", False, UPLOAD_PROGRESS_WIDTH, UPLOAD_PROGRESS_HEIGHT)
        _item_panel = ItemPanel(_ui, _tasks, _item_host, bridge, config, auth, _progress_host)
        _export_host = PaletteHost(_ui, bridge, EXPORT_PALETTE_ID, EXPORT_TITLE, "export", False, EXPORT_WIDTH, EXPORT_HEIGHT, False)
        _export_dialog = ExportDialog(_export_host, bridge, _tasks, config, auth, _item_panel)
        menu_commands = [
            RibbonCommand(MENU_OPEN_COMMAND_ID, "Open Fusion Manage Item",
                          "Open the Fusion Manage item of the selected component.",
                          _item_panel.open_from_menu,
                          _icon("item"), needs_setup=True),
            RibbonCommand(MENU_PUBLISH_COMMAND_ID, "Publish Fusion Manage Item",
                          PUBLISH_TOOLTIP,
                          _publish_host.show_centered,
                          _icon("publish"), needs_setup=True, root_only=True, context="design"),
            RibbonCommand(MENU_UPLOAD_STEP_COMMAND_ID, "Export STEP File",
                          "Export the open design as a STEP file and attach it to the Fusion Manage item of the selected component.",
                          _item_panel.upload_selected_step,
                          _icon("upload_step"), needs_setup=True, context="design"),
            RibbonCommand(MENU_UPLOAD_DRAWING_COMMAND_ID, UPLOAD_DRAWING_NAME,
                          UPLOAD_DRAWING_TOOLTIP,
                          _item_panel.upload_drawing,
                          _icon("upload_drawing"), needs_setup=True, needs_drawing=True, root_only=True, context="drawing"),
        ]
        _item_menu = ItemContextMenu(_ui, menu_commands)
        open_item = RibbonCommand(ITEM_COMMAND_ID, "Open Fusion Manage Item",
                                  "Open the Fusion Manage item of the selected component, or of the open design or drawing.",
                                  _item_panel.open_selected,
                                  _icon("item"), needs_setup=True)
        publish_item = RibbonCommand(PUBLISH_COMMAND_ID, "Publish Fusion Manage Item",
                                     PUBLISH_TOOLTIP,
                                     _publish_host.show_centered,
                                     _icon("publish"), needs_setup=True)
        # Not held back by the setup or the drawing loading: the Export window says what is missing, and which destination that leaves off.
        export = RibbonCommand(EXPORT_COMMAND_ID, "Export",
                               "Export the open design or drawing, and attach the file to its item or component in Fusion Manage.",
                               _export_dialog.show,
                               _icon("upload_step"))
        administration = RibbonGroup([
            RibbonCommand(JOBS_COMMAND_ID, "Job Queue", JOBS_TOOLTIP,
                          _jobs_host.show_centered,
                          _icon("jobs"), needs_setup=True),
            RibbonCommand(COMMAND_ID, "Preferences",
                          "Open the Fusion Manage panel: connection and settings.",
                          _palette_host.show,
                          _icon("settings")),
        ], RIBBON_ADMINISTRATION_NAME, _icon("settings"))
        # Panels appear in this order, Export on the left. A drawing is not published (that is for the design), so it has no Publish.
        export_panel = RibbonPanel(RIBBON_EXPORT_PANEL_ID, RIBBON_EXPORT_PANEL_NAME, [RibbonGroup([export])])
        panels = {
            RIBBON_DESIGN_WORKSPACE: [export_panel, RibbonPanel(RIBBON_MERGED_PANEL_ID, RIBBON_MERGED_PANEL_NAME,
                                                                [RibbonGroup([open_item, publish_item]), administration])],
            RIBBON_DRAWING_WORKSPACE: [export_panel, RibbonPanel(RIBBON_MERGED_PANEL_ID, RIBBON_MERGED_PANEL_NAME,
                                                                 [RibbonGroup([open_item]), administration])],
        }
        _ribbon = Ribbon(_ui, panels, RIBBON_HOST_TAB_NAME)
        _ribbon.register()
        # Everything but Preferences needs the Items workspace set up; it stays greyed out until it is. The drawing's PDF also
        # needs the drawing loaded: looked at again on Fusion's document and workspace events, and every few seconds while a drawing loads.
        _gate = SetupGate(_ui, menu_commands + _ribbon.commands(), config.items_setup_problem, drawing_source.problem)
        _watcher = GateWatcher(_ui, _tasks, _gate, lambda: drawing_source.active_drawing() is not None and bool(drawing_source.problem()),
                               on_event=hub.refresh)
        _watcher.check()
        config.on_change(lambda: _tasks.post(_gate.refresh))   # saving the settings can come from any thread
        log.info("Add-in started")
    except Exception:  # noqa: BLE001 - report to the user instead of failing silently
        log.exception("Add-in failed to start")
        if _ui:
            _ui.messageBox(f"Failed to start:\n{traceback.format_exc()}")


def stop(context) -> None:
    """Add-in stop: remove every UI element this add-in created."""
    try:
        if _palette_host:
            _palette_host.dispose()
        if _publish_host:
            _publish_host.dispose()
        if _progress_host:
            _progress_host.dispose()
        if _export_host:
            _export_host.dispose()
        if _jobs_host:
            _jobs_host.dispose()
        if _item_host:
            _item_host.dispose()
        if _item_panel:
            _item_panel.dispose()
        if _item_menu:
            _item_menu.dispose()
        if _watcher:
            _watcher.dispose()
        if _tasks:
            _tasks.dispose()
        if _ribbon:
            _ribbon.unregister()
        log.info("Add-in stopped")
    except Exception:  # noqa: BLE001
        log.exception("Add-in failed to stop cleanly")
    finally:
        shutdown_logging()

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
from src.config.hub_languages import HubLanguages  # noqa: E402
from src.config.config_service import ConfigService  # noqa: E402
from src.core.cancel import ADDIN  # noqa: E402
from src.core.logging_setup import get_logger, shutdown_logging  # noqa: E402
from src.ui import drawing_source  # noqa: E402
from src.ui import ribbon as ribbon_module  # noqa: E402
from src.ui.actions import register_actions  # noqa: E402
from src.ui.actions.language_actions import register_language_actions, start_language  # noqa: E402
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
    EXPORT_WIDTH,
    ITEM_COMMAND_ID,
    ITEM_HEIGHT,
    ITEM_PALETTE_ID,
    ITEM_WIDTH,
    JOBS_COMMAND_ID,
    JOBS_HEIGHT,
    JOBS_PALETTE_ID,
    JOBS_WIDTH,
    MENU_OPEN_COMMAND_ID,
    MENU_PUBLISH_COMMAND_ID,
    MENU_UPLOAD_DRAWING_COMMAND_ID,
    MENU_UPLOAD_STEP_COMMAND_ID,
    PUBLISH_HEIGHT,
    PUBLISH_PALETTE_ID,
    PUBLISH_WIDTH,
    RIBBON_DESIGN_WORKSPACE,
    RIBBON_DRAWING_WORKSPACE,
    RIBBON_EXPORT_PANEL_ID,
    RIBBON_HOST_TAB_NAME,
    RIBBON_MERGED_PANEL_ID,
    SETTINGS_PALETTE_ID,
    UPLOAD_PROGRESS_HEIGHT,
    UPLOAD_PROGRESS_PALETTE_ID,
    UPLOAD_PROGRESS_WIDTH,
)
from src.ui.ribbon import Ribbon, RibbonCommand, RibbonGroup, RibbonPanel  # noqa: E402
from src.ui.ui_text import (  # noqa: E402
    export_step_name,
    export_step_tooltip,
    export_title,
    item_command_name,
    item_title,
    jobs_title,
    jobs_tooltip,
    menu_open_tooltip,
    menu_publish_name,
    preferences_name,
    preferences_tooltip,
    publish_title,
    publish_tooltip,
    ribbon_administration_name,
    ribbon_export_tooltip,
    ribbon_merged_panel_name,
    ribbon_open_tooltip,
    settings_title,
    start_failed,
    upload_drawing_name,
    upload_drawing_tooltip,
    upload_title,
)

log = get_logger()

def _icon(folder: str) -> str:
    """The folder of the icons (``16x16.svg``...) named ``folder`` under ``resources/images``."""
    return os.path.join(_ADDIN_DIR, "resources", "images", folder)


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
_bridge = None


# ---- Active hub ---------------------------------------------------------------

_config = None
_hub_languages = None   # the languages the active hub shares, found in a folder of that hub


def sync_hub() -> None:
    """Tell the settings which hub is active. Main thread (it asks Fusion): called at start, before each command, and whenever the
    commands' availability is looked at again (a document or workspace was opened). Settings are kept for each hub."""
    try:
        hub = adsk.core.Application.get().data.activeHub
        if _config is not None:
            if _config.use_hub(hub.id if hub else "", hub.name if hub else "") and _hub_languages is not None:
                _hub_languages.use(hub.id if hub else "")   # another hub shares other languages
    except Exception:  # noqa: BLE001 - never raise into Fusion
        log.exception("Could not read the active hub")


def setup_problem() -> str:
    """Why the active hub's settings are not complete (the active hub is looked at first)."""
    sync_hub()
    return _config.items_setup_problem()


def _push_to_panels(action: str, data: str) -> None:
    """Send ``data`` to every panel, from any thread: the send itself is done on the main thread, by a custom event."""
    def send() -> None:
        for host in (_palette_host, _publish_host, _jobs_host, _item_host, _export_host, _progress_host):   # the panels that can show a hub's state, or an upload's
            try:
                if host:
                    host.send(action, data)
            except Exception:  # noqa: BLE001 - one panel that cannot be reached must not keep the others from the answer
                log.exception("Could not send %s to a panel", action)
    if _tasks:
        _tasks.post(send)


# ---- Fusion lifecycle -------------------------------------------------------

REBUILD_EVENT_ID = "MfgToFm_Rebuild"
_rebuilding = False   # stop() and run() are being done again for a new language: the event that asked for it stays
_rebuild_handler = None


class _RebuildHandler(adsk.core.CustomEventHandler):
    """Stops the add-in and starts it again, on the main thread after the palette message that asked for it has been answered."""

    def notify(self, args) -> None:
        global _rebuilding
        _rebuilding = True
        try:
            stop(None)
            run(None)
        except Exception:  # noqa: BLE001 - boundary to Fusion, must not raise
            log.exception("Could not make the ribbon again in the new language")
        finally:
            _rebuilding = False


def _rebuild_for_language() -> None:
    """The ribbon's and the panels' text is fixed once built: make them again, in the language now in use."""
    try:
        adsk.core.Application.get().fireCustomEvent(REBUILD_EVENT_ID, "")
    except Exception:  # noqa: BLE001 - the panels have been told to load again; the ribbon follows after a restart of Fusion
        log.exception("Could not ask for the ribbon to be made again")


def _register_rebuild() -> None:
    global _rebuild_handler
    if _rebuild_handler is not None:
        return   # kept across the stop and run of a rebuild: it is the handler that is running
    app = adsk.core.Application.get()
    try:
        app.unregisterCustomEvent(REBUILD_EVENT_ID)   # left over from a previous run of the add-in
    except RuntimeError:
        pass
    _rebuild_handler = _RebuildHandler()
    app.registerCustomEvent(REBUILD_EVENT_ID).add(_rebuild_handler)


def _unregister_rebuild() -> None:
    global _rebuild_handler
    if _rebuilding or _rebuild_handler is None:
        return
    try:
        app = adsk.core.Application.get()
        app.unregisterCustomEvent(REBUILD_EVENT_ID)
    except RuntimeError:
        pass
    _rebuild_handler = None

def _close_settings(_payload) -> dict:
    """Close the settings panel: a member who does not pick a Configuration File has nothing to set up."""
    if _tasks and _palette_host:
        _tasks.post(_palette_host.hide)
    return {}


def run(context) -> None:
    """Add-in start: compose services, palette and ribbon."""
    global _bridge, _config, _hub_languages, _ui, _palette_host, _publish_host, _jobs_host, _progress_host, _export_host, _export_dialog, _item_host, _item_panel, _item_menu, _ribbon, _tasks, _gate, _watcher
    ADDIN.reset()   # work is allowed again (the add-in may be started once more in the same process)
    try:
        start_language()   # first: every title, name and tooltip below is built in the user's language (fixed once built: a change makes them again)
        _ui = adsk.core.Application.get().userInterface
        _register_rebuild()

        bridge = _bridge = MessageBridge()
        _tasks = UiThread()
        badge = JobsBadge(_ui, _tasks, JOBS_COMMAND_ID, jobs_tooltip(), os.path.join(_ADDIN_DIR, "resources", "images"))
        config, auth = ConfigService(hub_aware=True), AuthService()
        _config = config
        ribbon_module.before_command = sync_hub
        _hub_languages = HubLanguages()
        sync_hub()   # the settings are those of the hub that is open now, and so are the languages it shares
        roles = register_actions(bridge, config, auth, FileDialogs(_ui), badge, JobAlerts(_ui, _tasks), _tasks.post, _hub_languages)
        register_language_actions(bridge, _push_to_panels, _rebuild_for_language)

        _palette_host = PaletteHost(_ui, bridge, SETTINGS_PALETTE_ID, settings_title(), "settings")
        bridge.register("close_settings", _close_settings)
        _publish_host = PaletteHost(_ui, bridge, PUBLISH_PALETTE_ID, publish_title(), "publish", False, PUBLISH_WIDTH, PUBLISH_HEIGHT, fresh=True)
        _jobs_host = PaletteHost(_ui, bridge, JOBS_PALETTE_ID, jobs_title(), "jobs", False, JOBS_WIDTH, JOBS_HEIGHT)
        _item_host = PaletteHost(_ui, bridge, ITEM_PALETTE_ID, item_title(), "item", True, ITEM_WIDTH, ITEM_HEIGHT)
        _progress_host = PaletteHost(_ui, bridge, UPLOAD_PROGRESS_PALETTE_ID, upload_title(), "progress", False, UPLOAD_PROGRESS_WIDTH, UPLOAD_PROGRESS_HEIGHT)
        _item_panel = ItemPanel(_ui, _tasks, _item_host, bridge, config, auth, _progress_host, _publish_host.show)
        _export_host = PaletteHost(_ui, bridge, EXPORT_PALETTE_ID, export_title(), "export", True, EXPORT_WIDTH, EXPORT_HEIGHT)
        _export_dialog = ExportDialog(_export_host, bridge, _tasks, config, auth, _item_panel)
        bridge.set_pusher(_push_to_panels)   # background work can now tell the panels when it is done, instead of being asked
        menu_commands = [
            RibbonCommand(MENU_OPEN_COMMAND_ID, item_command_name(),
                          menu_open_tooltip(),
                          _item_panel.open_from_menu,
                          _icon("item"), needs_setup=True),
            RibbonCommand(MENU_PUBLISH_COMMAND_ID, menu_publish_name(),
                          publish_tooltip(),
                          _publish_host.show,
                          _icon("publish"), needs_setup=True, root_only=True, context="design"),
            RibbonCommand(MENU_UPLOAD_STEP_COMMAND_ID, export_step_name(),
                          export_step_tooltip(),
                          _item_panel.upload_selected_step,
                          _icon("upload_step"), needs_setup=True, context="design"),
            RibbonCommand(MENU_UPLOAD_DRAWING_COMMAND_ID, upload_drawing_name(),
                          upload_drawing_tooltip(),
                          _item_panel.upload_drawing,
                          _icon("upload_drawing"), needs_setup=True, needs_drawing=True, root_only=True, context="drawing"),
        ]
        _item_menu = ItemContextMenu(_ui, menu_commands)
        open_item = RibbonCommand(ITEM_COMMAND_ID, item_command_name(),
                                  ribbon_open_tooltip(),
                                  _item_panel.open_selected,
                                  _icon("item"), needs_setup=True)
        # Not held back by the setup or the drawing loading: the Export window says what is missing, and which destination that leaves off.
        export = RibbonCommand(EXPORT_COMMAND_ID, export_title(),
                               ribbon_export_tooltip(),
                               _export_dialog.show,
                               _icon("upload_step"))
        administration = RibbonGroup([
            RibbonCommand(JOBS_COMMAND_ID, jobs_title(), jobs_tooltip(),
                          _jobs_host.show,
                          _icon("jobs"), needs_setup=True),
            RibbonCommand(COMMAND_ID, preferences_name(),
                          preferences_tooltip(),
                          _palette_host.show,
                          _icon("settings")),
        ], ribbon_administration_name(), _icon("settings"))
        # Panels appear in this order, Export on the left. Publishing is opened from the item panel and the right-click menu, not the ribbon.
        export_panel = RibbonPanel(RIBBON_EXPORT_PANEL_ID, export_title(), [RibbonGroup([export])])
        panels = {
            RIBBON_DESIGN_WORKSPACE: [export_panel, RibbonPanel(RIBBON_MERGED_PANEL_ID, ribbon_merged_panel_name(),
                                                                [RibbonGroup([open_item]), administration])],
            RIBBON_DRAWING_WORKSPACE: [export_panel, RibbonPanel(RIBBON_MERGED_PANEL_ID, ribbon_merged_panel_name(),
                                                                 [RibbonGroup([open_item]), administration])],
        }
        _ribbon = Ribbon(_ui, panels, RIBBON_HOST_TAB_NAME)
        _ribbon.register()
        # Everything but Preferences needs the Items workspace set up; it stays greyed out until it is. The drawing's PDF also
        # needs the drawing loaded: looked at again on Fusion's document and workspace events, and every few seconds while a drawing loads.
        _gate = SetupGate(_ui, menu_commands + _ribbon.commands(), setup_problem, drawing_source.problem)
        _watcher = GateWatcher(_ui, _tasks, _gate, lambda: drawing_source.active_drawing() is not None and bool(drawing_source.problem()))
        _watcher.check()
        config.on_change(lambda: _tasks.post(_gate.refresh))   # saving the settings can come from any thread
        log.info("Add-in started")
    except Exception:  # noqa: BLE001 - report to the user instead of failing silently
        log.exception("Add-in failed to start")
        if _ui:
            _ui.messageBox(start_failed(traceback.format_exc()))


def stop(context) -> None:
    """Add-in stop: remove every UI element this add-in created."""
    ADDIN.cancel()   # every request still waiting on the network ends now, so no thread outlives the add-in holding a connection
    try:
        if _bridge:
            _bridge.set_pusher(None)   # nothing may be sent to panels that are going away
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
        _unregister_rebuild()
        log.info("Add-in stopped")
    except Exception:  # noqa: BLE001
        log.exception("Add-in failed to stop cleanly")
    finally:
        if not _rebuilding:
            shutdown_logging()   # a rebuild goes on logging to the same file

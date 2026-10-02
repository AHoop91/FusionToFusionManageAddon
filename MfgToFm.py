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
from src.core.logging_setup import get_logger, shutdown_logging  # noqa: E402
from src.ui.actions import register_actions  # noqa: E402
from src.ui.file_dialogs import FileDialogs  # noqa: E402
from src.ui.message_bridge import MessageBridge  # noqa: E402
from src.ui.job_alerts import JobAlerts  # noqa: E402
from src.ui.jobs_badge import JobsBadge  # noqa: E402
from src.ui.palette_host import PaletteHost  # noqa: E402
from src.ui.ui_thread import UiThread  # noqa: E402
from src.core.constants import (  # noqa: E402
    COMMAND_ID,
    JOBS_COMMAND_ID,
    JOBS_HEIGHT,
    JOBS_PALETTE_ID,
    JOBS_TITLE,
    JOBS_WIDTH,
    PUBLISH_COMMAND_ID,
    PUBLISH_PALETTE_ID,
    PUBLISH_TITLE,
    RIBBON_PANEL_ID,
    RIBBON_PANEL_NAME,
    RIBBON_PUBLISH_PANEL_ID,
    RIBBON_PUBLISH_PANEL_NAME,
    RIBBON_WORKSPACE_IDS,
    SETTINGS_PALETTE_ID,
    SETTINGS_TITLE,
)
from src.ui.ribbon import Ribbon, RibbonCommand, RibbonPanel  # noqa: E402

log = get_logger()

JOBS_TOOLTIP = "Show the job queue: publishes that are waiting, running and finished."

# ---- Add-in state -----------------------------------------------------------
# Module-level references keep objects (and their Fusion handlers) alive for
# the add-in lifetime.
_ui = None
_palette_host = None
_publish_host = None
_jobs_host = None
_ribbon = None
_tasks = None


# ---- Fusion lifecycle -------------------------------------------------------

def run(context) -> None:
    """Add-in start: compose services, palette and ribbon."""
    global _ui, _palette_host, _publish_host, _jobs_host, _ribbon, _tasks
    try:
        _ui = adsk.core.Application.get().userInterface

        bridge = MessageBridge()
        _tasks = UiThread()
        badge = JobsBadge(_ui, _tasks, JOBS_COMMAND_ID, JOBS_TOOLTIP, os.path.join(_ADDIN_DIR, "resources"))
        register_actions(bridge, ConfigService(), AuthService(), FileDialogs(_ui), badge, JobAlerts(_ui, _tasks))

        _palette_host = PaletteHost(_ui, bridge, SETTINGS_PALETTE_ID, SETTINGS_TITLE, "settings")
        _publish_host = PaletteHost(_ui, bridge, PUBLISH_PALETTE_ID, PUBLISH_TITLE, "publish")
        _jobs_host = PaletteHost(_ui, bridge, JOBS_PALETTE_ID, JOBS_TITLE, "jobs", False, JOBS_WIDTH, JOBS_HEIGHT)
        # Panels appear in this order. Add further buttons or panels here; the
        # ribbon needs no other changes.
        _ribbon = Ribbon(_ui, RIBBON_WORKSPACE_IDS, [
            RibbonPanel(RIBBON_PUBLISH_PANEL_ID, RIBBON_PUBLISH_PANEL_NAME, [
                RibbonCommand(PUBLISH_COMMAND_ID, "Publish Item",
                              "Preview what will be published to Fusion Manage for the current item.",
                              _publish_host.show,
                              os.path.join(_ADDIN_DIR, "resources", "publish")),
                RibbonCommand(JOBS_COMMAND_ID, "Job Queue", JOBS_TOOLTIP,
                              _jobs_host.show,
                              os.path.join(_ADDIN_DIR, "resources", "jobs")),
            ]),
            RibbonPanel(RIBBON_PANEL_ID, RIBBON_PANEL_NAME, [
                RibbonCommand(COMMAND_ID, "Settings",
                              "Open the Fusion Manage panel: connection and settings.",
                              _palette_host.show,
                              os.path.join(_ADDIN_DIR, "resources", "settings")),
            ]),
        ])
        _ribbon.register()
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
        if _jobs_host:
            _jobs_host.dispose()
        if _tasks:
            _tasks.dispose()
        if _ribbon:
            _ribbon.unregister()
        log.info("Add-in stopped")
    except Exception:  # noqa: BLE001
        log.exception("Add-in failed to stop cleanly")
    finally:
        shutdown_logging()

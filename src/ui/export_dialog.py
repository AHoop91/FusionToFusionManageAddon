"""The Export window: the file to make from the open design or drawing, and where in Fusion Manage to attach it.

The page (``web/export``) asks what is on offer (``export_context``), then says what was chosen (``export_run``). What is offered is worked
out again at each call, since the open document can change while the window is open.

A destination is off when it is not set up (the Items workspace not being configured in Preferences, or no connection), and also when the
user may not attach files to its workspace. The permissions are read from Fusion Manage once when the window opens, on a worker thread so
Fusion is not held up, and the page is told the result (``export_access``); until then the destinations say they are being checked.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..auth.errors import AuthError
from ..config.config_service import ConfigService
from ..config.export_models import COMPONENT, ITEM
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID
from ..core.cancel import Cancelled
from ..core.logging_setup import get_logger
from ..fm.client import FmApiError, FmClient
from ..fm.components import ComponentService
from ..fm.permissions import ATTACH_PERMISSIONS, denial
from . import drawing_source
from .export_options import DESIGN, DRAWING, describe, formats_for
from .item_panel import ItemPanel
from .message_bridge import MessageBridge
from .palette_host import PaletteHost
from .ui_thread import UiThread

log = get_logger("export_dialog")

ITEM_NOT_CONFIGURED = "Item is not configured. Complete it in Preferences."
LABELS = {ITEM: "Item", COMPONENT: "Component"}


def _document() -> str:
    """The kind of document that is open: "drawing", "design", or "" for anything else."""
    if drawing_source.active_drawing() is not None:
        return DRAWING
    return DESIGN if adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is not None else ""


class ExportDialog:
    """Shows the Export window and carries out what is chosen in it."""

    def __init__(self, host: PaletteHost, bridge: MessageBridge, tasks: UiThread, config: ConfigService, auth: AuthService,
                 panel: ItemPanel) -> None:
        self._host = host
        self._tasks = tasks
        self._config = config
        self._auth = auth
        self._panel = panel
        self._access: Dict[str, str] = {}   # for each destination, why the user may not attach to it ("" when they may); empty until read
        self._checking = False
        bridge.register("export_context", self._context)
        bridge.register("export_files", self._files)
        bridge.register("export_run", self._run)
        bridge.register("export_close", self._close)

    def show(self) -> None:
        """Open the window afresh in the middle of Fusion (it is closed, not hidden, so it is read again and centred each time). UI thread."""
        self._access, self._checking = {}, False
        self._panel.reset_export()
        self._host.dispose()
        self._host.show()

    # ---- What can be attached to ----------------------------------------------------

    def _setup_reasons(self) -> Dict[str, str]:
        """For each destination, why it cannot be used until something is set up ("" when nothing is missing). Needs no call to Fusion Manage."""
        try:
            connection = " ".join(self._config.effective_settings().validate())
        except Exception as exc:  # noqa: BLE001 - e.g. shared settings that cannot be read: the reason is shown
            connection = str(exc)
        return {ITEM: ITEM_NOT_CONFIGURED if self._config.items_setup_problem() else "",
                COMPONENT: f"{connection} Complete it in Preferences." if connection else ""}

    def _item_denial(self, client: FmClient) -> str:
        kind = KINDS_BY_ID[ITEMS_KIND]
        return denial(client, self._config.config.workspaces.get(ITEMS_KIND).workspace_id, ATTACH_PERMISSIONS, kind.title, "attach files to")

    def _component_denial(self, client: FmClient) -> str:
        workspace_id = ComponentService(client).workspace_id()
        if not workspace_id:
            return "No workspace called Components could be found in Fusion Manage."
        return denial(client, workspace_id, ATTACH_PERMISSIONS, "Components", "attach files to")

    @staticmethod
    def _asked(check: Callable[[FmClient], str], client: FmClient) -> str:
        """What ``check`` says, or why it could not be asked."""
        try:
            return check(client)
        except Cancelled:   # the window was closed
            raise
        except (FmApiError, AuthError) as exc:
            return f"Permissions could not be checked: {exc}"
        except Exception as exc:  # noqa: BLE001 - shown to the user, never raised into a thread nobody watches
            log.exception("Could not check the permissions")
            return f"Permissions could not be checked: {exc}"

    def _check_access(self, setup: Dict[str, str]) -> None:
        """Read the user's permissions in the workspaces that are set up (a worker thread), then tell the page. A destination that is not set
        up keeps its setup reason and is not asked about."""
        reasons = dict(setup)
        try:
            client = FmClient(self._config.effective_settings(), self._auth, self._panel.export_token)
            checks = {key: check for key, check in ((ITEM, self._item_denial), (COMPONENT, self._component_denial)) if not setup[key]}
            with ThreadPoolExecutor(max_workers=2) as pool:   # one workspace does not wait for the other
                asked = {key: pool.submit(self._asked, check, client) for key, check in checks.items()}
                for key, future in asked.items():
                    reasons[key] = future.result()
        except Cancelled:   # the window was closed: nobody waits for the answer
            log.info("The check of the permissions to attach files was cancelled")
            return
        except Exception as exc:  # noqa: BLE001 - as above
            log.exception("Could not start the permission check")
            for key in reasons:
                reasons[key] = reasons[key] or f"Permissions could not be checked: {exc}"
        log.info("Export permissions: %s", reasons)
        self._tasks.post(lambda: self._checked(reasons))

    def _checked(self, reasons: Dict[str, str]) -> None:
        """Keep what the permission check found and tell the page. UI thread."""
        self._access, self._checking = reasons, False
        self._host.send("export_access", json.dumps({"ok": True, "result": {"reasons": reasons}, "error": None}))

    # ---- The page's calls -----------------------------------------------------------

    def _context(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the window shows: the formats of the open document, the destinations (why one is off, or that it is still being checked), and
        what is exported."""
        document = _document()
        number, problem = self._panel.export_target() if document else ("", "Open a design or a drawing to export.")
        setup = self._setup_reasons()
        if not self._access and not self._checking:
            self._checking = True
            threading.Thread(target=self._check_access, args=(setup,), daemon=True).start()
            if document and not problem:
                self._panel.warm_export_target(self._item_found)   # while the user chooses, so Find item has nothing left to read
        destinations = []
        for key in (ITEM, COMPONENT):
            reason = setup[key] or self._access.get(key, "")
            destinations.append({"key": key, "label": LABELS[key], "reason": reason,
                                 "checking": not reason and key not in self._access})
        usable = [d["key"] for d in destinations if not d["reason"] and not d["checking"]]
        exports = self._config.config.exports
        return {"target": number, "description": self._panel.export_description() if number else "", "problem": problem,
                "formats": [describe(key) for key in formats_for(document)],
                "destinations": destinations, "destination": usable[0] if usable else "",
                "defaults": {key: exports.destination_of(key) for key in formats_for(document)}}   # set in Preferences ▸ Export

    def _item_found(self, part_number: str, item_number: str) -> None:
        """Tell the page the item number of what is exported, for its title (the window shows a grey bar until this, the item number taking longer
        than the part number to read). A worker thread."""
        message = json.dumps({"ok": True, "result": {"target": part_number, "item_number": item_number}, "error": None})
        self._tasks.post(lambda: self._host.send("export_item", message))

    def _files(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the files attached where the export would go, to tell the page whether it adds a file or makes a new version of one
        (``export_files_found``, with the format and destination asked about, so the page can tell it from an answer to an earlier choice)."""
        key, destination = str(payload.get("format") or ""), str(payload.get("destination") or "")
        if key not in formats_for(_document()) or destination not in (ITEM, COMPONENT):
            raise ValueError("Choose a format and where to attach the file.")

        def found(result: Dict[str, Any]) -> None:
            message = json.dumps({"ok": True, "result": dict(result, format=key, destination=destination), "error": None})
            self._tasks.post(lambda: self._host.send("export_files_found", message))

        self._panel.export_files(key, destination, str(payload.get("target") or ""), found)
        return {"started": True}

    def _run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start the export the window asked for; raises (shown in the window) when what it asked for cannot be done now."""
        key, destination = str(payload.get("format") or ""), str(payload.get("destination") or "")
        if key not in formats_for(_document()):
            raise ValueError("That format cannot be made from the open document. It may have changed: open the window again.")
        if destination not in (ITEM, COMPONENT):
            raise ValueError("Choose where to attach the file.")
        reason = self._setup_reasons()[destination] or self._access.get(destination)
        if reason is None:
            raise ValueError("Your permissions are still being checked. Try again in a moment.")
        if reason:
            raise ValueError(reason)
        number, problem = self._panel.export_target()
        if problem:
            raise ValueError(problem)
        if str(payload.get("target") or number) != number:
            raise ValueError(f"The selection changed to {number} since this window opened. Open it again to export that.")
        log.info("Export %s to the %s", key, destination)
        self._panel.export(key, destination)   # the window stays open and follows it (``upload_status``)
        return {"started": True}

    def _close(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        self._panel.cancel_export()   # the window is going: what it was still reading is not wanted
        self._tasks.post(self._host.dispose)
        return {}

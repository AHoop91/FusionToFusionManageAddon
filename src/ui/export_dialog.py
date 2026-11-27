"""The Export window (UI layer): the file to make from the open design or drawing, and where in Fusion Manage to attach it.

The page (``web/export``) asks what is on offer (``export_context``), then says what was chosen (``export_run``). What is offered is worked
out again at each call, since the open document can change while the window is open.
What it reads from Fusion and Fusion Manage for the window, and the export itself, are ``ExportPanel`` (``export_panel.py``).

A destination is off when it is not set up (the Items workspace not being configured in Preferences, or no connection), and also when the
user may not attach files to its workspace. The permissions are read from Fusion Manage when the window opens, on a worker thread so
Fusion is not held up, and the page is told the result (``export_access``); until then the destinations say they are being checked. They
are read under one ``HubContext``, and again when the hub or the settings have changed since. When Fusion Manage does not accept the app at
all (its Client ID is not added there), the page is told so in ``denied``, and says it in place of the reasons, as the Item panel does.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..auth.errors import AuthError
from ..config.config_service import ConfigService
from ..config.export_models import COMPONENT, ITEM
from ..config.hub_context import HubContext, HubContexts
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID, kind_texts
from ..core.cancel import Cancelled
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..fm.client import WORKSPACES, FmApiError, FmClient
from ..fm.components import ComponentService
from ..fm.permissions import ATTACH_PERMISSIONS, REFUSED, denial
from . import drawing_source, fusion_selection
from .export_options import DESIGN, DRAWING, describe, formats_for
from .export_panel import ExportPanel
from .message_bridge import MessageBridge
from .palette_host import PaletteHost
from .ui_thread import UiThread

log = get_logger("export_dialog")


def _label(destination: str) -> str:
    """What the window calls a destination."""
    return t("app.destination_component") if destination == COMPONENT else t("app.destination_item")


def _document() -> str:
    """The kind of document that is open: "drawing", "design", or "" for anything else."""
    if drawing_source.active_drawing() is not None:
        return DRAWING
    return DESIGN if adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is not None else ""


class ExportDialog:
    """Shows the Export window and carries out what is chosen in it."""

    # Six collaborators, each a different one (the caller in ``main`` owns them all): over the guardrail of four, and not ones to bundle.
    def __init__(self, host: PaletteHost, bridge: MessageBridge, tasks: UiThread, config: ConfigService, auth: AuthService,
                 panel: ExportPanel) -> None:
        self._host = host
        self._tasks = tasks
        self._config = config
        self._contexts = HubContexts(config, auth.session)
        self._auth = auth
        self._panel = panel
        self._access: Dict[str, str] = {}   # for each destination, why the user may not attach to it ("" when they may); empty until read
        self._access_stamp = ""   # the stamp of the context ``_access`` was read under: read again when it is no longer the active one
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

    def show_selected(self) -> None:
        """Open the window for the component that was right-clicked: it is selected again first, as the window exports the selected component. UI thread."""
        fusion_selection.restore_menu_selection()
        self.show()

    # ---- What can be attached to ----------------------------------------------------

    def _setup(self) -> Tuple[Dict[str, str], Optional[HubContext]]:
        """For each destination, why it cannot be used until something is set up ("" when nothing is missing), and the context that says so.
        Settings that cannot be read (Shared Configuration) are the reason of both, with no context. Needs no call to Fusion Manage. UI thread."""
        context, reason = self._contexts.attempt()
        if context is None:
            return {key: reason for key in (ITEM, COMPONENT)}, None
        connection = " ".join(context.settings.validate())
        return {ITEM: t("app.item_not_configured") if context.items_problem else "",   # also when it is turned off: see ``_offered``
                COMPONENT: t("app.complete_in_preferences", problem=connection) if connection else ""}, context

    @staticmethod
    def _offered(context: Optional[HubContext]) -> Tuple[str, ...]:
        """The destinations the window offers: with the Items workspace turned off, files can only go to the component, so the item is not offered
        (and nothing is said about it)."""
        return (COMPONENT,) if context is not None and context.items_off else (COMPONENT, ITEM)

    def problem(self) -> str:
        """Why nothing can be exported to when no destination is set up, and nothing when one is: for the ribbon button. UI thread."""
        setup, context = self._setup()
        reasons = [setup[key] for key in self._offered(context)]
        return "" if "" in reasons else reasons[0]

    @staticmethod
    def _item_denial(client: FmClient, context: HubContext) -> str:
        kind = KINDS_BY_ID[ITEMS_KIND]
        return denial(client, context.cfg.workspace_id, ATTACH_PERMISSIONS, kind_texts(kind)[0], "attach files to")

    def _component_denial(self, client: FmClient) -> str:
        workspace_id = ComponentService(client).workspace_id()
        if not workspace_id:
            return t("app.no_components_workspace")
        return denial(client, workspace_id, ATTACH_PERMISSIONS, "Components", "attach files to")

    @staticmethod
    def _asked(check: Callable[[FmClient], str], client: FmClient) -> str:
        """What ``check`` says, or why it could not be asked."""
        try:
            return check(client)
        except Cancelled:   # the window was closed
            raise
        except (FmApiError, AuthError) as exc:
            return t("app.export_permissions_failed", reason=exc)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never raised into a thread nobody watches
            log.exception("Could not check the permissions")
            return t("app.export_permissions_failed", reason=exc)

    def _check_access(self, setup: Dict[str, str], context: HubContext) -> None:
        """Read the user's permissions in the workspaces that are set up (a worker thread), then tell the page. A destination that is not set
        up keeps its setup reason and is not asked about."""
        reasons = dict(setup)
        denied = ""   # said when Fusion Manage does not accept the app
        try:
            denied = self._read_reasons(setup, context, reasons)
        except Cancelled:   # the window was closed: nobody waits for the answer
            log.info("The check of the permissions to attach files was cancelled")
            return
        except Exception as exc:  # noqa: BLE001 - as above
            log.exception("Could not start the permission check")
            for key in reasons:
                reasons[key] = reasons[key] or t("app.export_permissions_failed", reason=exc)
        log.info("Export permissions: %s", reasons)
        self._tasks.post(lambda: self._checked(reasons, context.stamp, denied))

    def _read_reasons(self, setup: Dict[str, str], context: HubContext, reasons: Dict[str, str]) -> str:
        """Ask Fusion Manage about each destination that is set up and write why it is refused (or "") into ``reasons``. Returns the words
        for an app Fusion Manage does not accept at all, or "" when it does. A worker thread."""
        client = FmClient(context.settings, self._auth, self._panel.export_token)
        checks = {key: check for key, check in ((ITEM, lambda c: self._item_denial(c, context)), (COMPONENT, self._component_denial))
                  if not setup[key]}
        with ThreadPoolExecutor(max_workers=2) as pool:   # one workspace does not wait for the other
            asked = {key: pool.submit(self._asked, check, client) for key, check in checks.items()}
            for key, future in asked.items():
                reasons[key] = future.result()
        if not any(reasons[key] for key in checks) or not self._app_refused(client):   # asked only when something was refused: a 403 is not this
            return ""
        denied = t("app.export_no_permission")
        for key in checks:
            reasons[key] = denied
        return denied

    @staticmethod
    def _app_refused(client: FmClient) -> bool:
        """Whether the v3 API refuses the user's app itself (a 401 for the list of workspaces, which any signed-in user may read), as it does
        for a Client ID with no user mapped to it: not that the user lacks permission in one workspace."""
        try:
            client.get_json(f"{WORKSPACES}?offset=0&limit=1")
        except FmApiError as exc:
            return exc.status in REFUSED
        except Exception:  # noqa: BLE001 - not known to be refused: the reasons found stand
            return False
        return False

    def _checked(self, reasons: Dict[str, str], stamp: str, denied: str = "") -> None:
        """Keep what the permission check found, made under the context of ``stamp``, and tell the page. UI thread."""
        self._access, self._access_stamp, self._checking = reasons, stamp, False
        self._host.send("export_access", json.dumps({"ok": True, "result": {"reasons": reasons, "denied": denied}, "error": None}))

    # ---- The page's calls -----------------------------------------------------------

    def _context(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the window shows: the formats of the open document, the destinations (why one is off, or that it is still being checked), and
        what is exported."""
        document = _document()
        number, problem = self._panel.export_target() if document else ("", t("app.open_to_export"))
        setup, context = self._setup()
        self._start_access_check(setup, context, warm=bool(document) and not problem)
        destinations = self._destinations(setup, context)
        usable = [d["key"] for d in destinations if not d["reason"] and not d["checking"]]
        exports = self._config.config.exports
        name, description = self._panel.export_names() if number else ("", "")
        return {"target": number, "name": name, "description": description, "problem": problem,
                "formats": [describe(key) for key in formats_for(document)],
                "destinations": destinations, "destination": usable[0] if usable else "",
                "defaults": {key: exports.destination_of(key) for key in formats_for(document)}}   # set in Preferences ▸ Export

    def _start_access_check(self, setup: Dict[str, str], context: Optional[HubContext], warm: bool) -> None:
        """Drop permissions read under other settings than those now active, and start reading them when none are kept or being read. With
        ``warm``, also read what is exported ahead, while the user chooses, so Find item has nothing left to read. UI thread."""
        if not context:
            return
        if self._access and self._access_stamp != context.stamp:   # read under other settings than those now active: not to be shown
            self._access = {}
        if self._access or self._checking:
            return
        self._checking = True
        threading.Thread(target=self._check_access, args=(setup, context), daemon=True).start()
        if warm:
            self._panel.warm_export_target(self._item_found, self._thumbnail_found)
            self._panel.warm_export_items(lambda found: self._push("export_items", found))

    def _destinations(self, setup: Dict[str, str], context: Optional[HubContext]) -> List[Dict[str, Any]]:
        """The destinations as the page shows them: why one is off, whether it is still being checked, and whether it is hidden."""
        offered = self._offered(context)
        destinations = []
        for key in (COMPONENT, ITEM):
            reason = setup[key] or self._access.get(key, "")
            destinations.append({"key": key, "label": _label(key), "reason": reason,
                                 "checking": not reason and key not in self._access,
                                 "hidden": key not in offered})
        return destinations

    def _push(self, event: str, result: Dict[str, Any]) -> None:
        """Send the page ``result`` as ``event``, from a worker thread (the send is made on the UI thread)."""
        message = json.dumps({"ok": True, "result": result, "error": None})
        self._tasks.post(lambda: self._host.send(event, message))

    def _item_found(self, part_number: str, item_number: str) -> None:
        """Tell the page the item number of what is exported, for its title (the window shows a grey bar until this, the item number taking longer
        than the part number to read). A worker thread."""
        self._push("export_item", {"target": part_number, "item_number": item_number})

    def _thumbnail_found(self, part_number: str, url: str) -> None:
        """Tell the page the thumbnail of what is exported (a signed https address, shown beside the title). A worker thread."""
        self._push("export_thumbnail", {"target": part_number, "url": url})

    def _files(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the files attached where the export would go, to tell the page whether it adds a file or makes a new version of one
        (``export_files_found``, with the format and destination asked about, so the page can tell it from an answer to an earlier choice)."""
        key, destination = str(payload.get("format") or ""), str(payload.get("destination") or "")
        if key not in formats_for(_document()) or destination not in (ITEM, COMPONENT):
            raise ValueError(t("app.export_choose_format_destination"))
        item_id = self._chosen_item(destination, str(payload.get("target") or ""), str(payload.get("item") or ""))

        def found(result: Dict[str, Any]) -> None:
            self._push("export_files_found", dict(result, format=key, destination=destination, item=item_id))

        self._panel.export_files(key, destination, str(payload.get("target") or ""), found, item_id)
        return {"started": True}

    def _run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start the export the window asked for; raises (shown in the window) when what it asked for cannot be done now."""
        key, destination = str(payload.get("format") or ""), str(payload.get("destination") or "")
        if key not in formats_for(_document()):
            raise ValueError(t("app.export_format_unavailable"))
        if destination not in (ITEM, COMPONENT):
            raise ValueError(t("app.export_choose_destination"))
        self._require_usable(destination)
        number = str(payload.get("target") or "")   # what the window shows is what is exported, whatever is selected in Fusion now
        if not number:
            number, problem = self._panel.export_target()
            if problem:
                raise ValueError(problem)
        item_id = self._chosen_item(destination, number, str(payload.get("item") or ""))
        log.info("Export %s of %s to the %s%s", key, number, destination, f" {item_id}" if item_id else "")
        self._panel.export(key, destination, number, item_id)   # the window stays open and follows it (``upload_status``)
        return {"started": True}

    def _chosen_item(self, destination: str, number: str, item_id: str) -> str:
        """The item the table chose, for the item destination ("" for the component): raises (shown in the window) unless it is one of the items the
        table listed for the part, so a file is not attached to an id the page merely sent."""
        if destination != ITEM:
            return ""
        if not self._panel.knows_item(number, item_id):
            raise ValueError(t("app.export_choose_item"))
        return item_id

    def _require_usable(self, destination: str) -> None:
        """Raise (shown in the window) unless ``destination`` is set up and the permissions read for it allow attaching files. UI thread."""
        setup, context = self._setup()
        if context and self._access and self._access_stamp != context.stamp:
            raise ValueError(t("app.export_settings_changed"))
        reason = setup[destination] or self._access.get(destination)
        if reason is None:
            raise ValueError(t("app.export_permissions_checking"))
        if reason:
            raise ValueError(reason)

    def _close(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        self._panel.cancel_export()   # the window is going: what it was still reading is not wanted
        self._tasks.post(self._host.dispose)
        return {}

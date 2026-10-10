"""Show a Fusion Manage item in a palette inside Fusion (the Item panel).

The item is found by item number alone: the part number of the selected component (or of the open
design when nothing is selected) is searched in the configured items workspace. It can be opened from
the ribbon or from the right-click menu of a selected component in the browser or canvas.

The page (``web/item``) is drawn by the add-in from the item's sections and fields, not by Fusion
Manage's web UI, so it needs no separate sign-in. Finding and reading the item call Fusion Manage, so
they run on a worker thread; the page polls ``get_item_view`` for the answer.
"""

import os
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..auth.errors import AuthError
from ..config.config_service import ConfigService
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID
from ..core.constants import ITEM_COMMAND_NAME
from ..core.logging_setup import get_logger
from ..fm.attachments import AttachmentService
from ..fm.bom_view import BomViewService
from ..fm.associated_workflows import AssociatedWorkflowService
from ..fm.client import FmApiError, FmClient
from ..fm.item_view import ItemViewService
from ..fm.items import ItemService
from ..fm.permissions import VIEW_ITEMS, granted as granted_permissions
from ..fm.where_used import WhereUsedService
from .message_bridge import MessageBridge
from .palette_host import PaletteHost
from .ribbon import RibbonCommand, define_command
from .ui_thread import UiThread

log = get_logger("item_panel")

LOOKUPS_KEPT = 200   # answers held for the page to read before the oldest finished ones are dropped
RUNNABLE = (".exe", ".com", ".bat", ".cmd", ".msi", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".scr", ".lnk", ".jar", ".hta", ".reg", ".dll", ".cpl", ".py", ".sh", ".app", ".command")


class ItemNotFound(Exception):
    """No item in the workspace has this item number."""

    def __init__(self, number: str) -> None:
        super().__init__(f"No item exists for {number}.")
        self.number = number


class NoAccess(Exception):
    """The user may not view the Items workspace."""

    def __init__(self) -> None:
        super().__init__(f"Insufficient permissions to view the {KINDS_BY_ID[ITEMS_KIND].title} workspace.")


def _answer(**changes: Any) -> Dict[str, Any]:
    """An answer of the page's poll: nothing found yet, with ``changes`` (``missing`` is an item number with no item, ``denied`` a message)."""
    return {"pending": False, "ok": False, "message": "", "view": None, "missing": "", "denied": "", **changes}


def _component_of(entity: Any) -> Optional[adsk.fusion.Component]:
    occurrence = adsk.fusion.Occurrence.cast(entity)
    return occurrence.component if occurrence is not None else adsk.fusion.Component.cast(entity)


def _selected_part_number() -> str:
    """Part number of the selected component, else of the open design ("" if neither has one). Runs on the UI thread."""
    app = adsk.core.Application.get()
    selections = app.userInterface.activeSelections
    for index in range(selections.count):
        component = _component_of(selections.item(index).entity)
        if component is not None:
            return str(component.partNumber or "").strip()
    design = adsk.fusion.Design.cast(app.activeProduct)
    return str(design.rootComponent.partNumber or "").strip() if design is not None else ""


def _open_file(path: str) -> None:
    """Open a file with its default program; a program or script is not run, its folder is shown instead."""
    if os.path.splitext(path)[1].lower() in RUNNABLE:
        path = os.path.dirname(path)
    if hasattr(os, "startfile"):
        os.startfile(path)   # Windows
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class ItemPanel:
    """Finds an item by number and shows it in the item palette."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, host: PaletteHost, bridge: MessageBridge,
                 config: ConfigService, auth: AuthService) -> None:
        self._ui = ui
        self._tasks = tasks
        self._host = host
        self._config = config
        self._auth = auth
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = _answer(seq=0)
        self._number = ""   # the item number the panel shows, for Refresh
        bridge.register("get_item_view", self._status)
        bridge.register("refresh_item_view", self._refresh)
        bridge.register("open_attachment", self._open_attachment)
        bridge.register("where_used_load", self._where_used_load)
        bridge.register("where_used_result", self._lookup_result)
        bridge.register("files_load", self._files_load)
        bridge.register("files_result", self._lookup_result)
        bridge.register("workflows_load", self._workflows_load)
        bridge.register("workflows_result", self._lookup_result)
        bridge.register("bom_load", self._bom_load)
        bridge.register("bom_result", self._lookup_result)
        self._lookups: Dict[str, Dict[str, Any]] = {}   # request id (from the page) -> its answer

    def _where_used_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the parents of an item (or of one of those parents, given its ``up`` link); the page polls for them."""
        workspace_id, item_id, up = self._workspace_id(payload), str(payload.get("item_id") or ""), str(payload.get("up") or "")
        return self._lookup(payload, lambda client: WhereUsedService(client).read(workspace_id, item_id, up))

    def _files_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the item's files; the page polls for them."""
        workspace_id, item_id, item_urn = self._workspace_id(payload), str(payload.get("item_id") or ""), str(payload.get("item_urn") or "")
        return self._lookup(payload, lambda client: AttachmentService(client).files(workspace_id, item_id, item_urn))

    def _workflows_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the associated workflows that reference the item; the page polls for them."""
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        return self._lookup(payload, lambda client: AssociatedWorkflowService(client).read(workspace_id, item_id))

    def _bom_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the item's bill of materials; the page polls for it."""
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        view_id, flat = str(payload.get("view_id") or ""), bool(payload.get("flat"))
        return self._lookup(payload, lambda client: BomViewService(client).read(workspace_id, item_id, view_id, flat))

    @staticmethod
    def _workspace_id(payload: Dict[str, Any]) -> str:
        """The workspace id of a look-up (the item id is checked with it)."""
        workspace_id, item_id = str(payload.get("workspace_id") or ""), str(payload.get("item_id") or "")
        if not (str(payload.get("request") or "") and workspace_id and item_id):
            raise ValueError("Which item to look up was not given.")
        return workspace_id

    def _lookup(self, payload: Dict[str, Any], work: Callable[[FmClient], Any]) -> Dict[str, Any]:
        """Run ``work`` on a worker thread; the page asks for its answer by the request id it gave."""
        request = str(payload["request"])
        with self._lock:
            if len(self._lookups) > LOOKUPS_KEPT:   # the page has long read the old answers
                for key in [k for k, v in self._lookups.items() if not v["pending"]][:LOOKUPS_KEPT // 2]:
                    del self._lookups[key]
            self._lookups[request] = {"pending": True, "ok": False, "message": "", "result": None}
        threading.Thread(target=self._run_lookup, args=(request, work), daemon=True).start()
        return {"started": True}

    def _lookup_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = str(payload.get("request") or "")
        with self._lock:
            state = self._lookups.get(request) or {"pending": False, "ok": False, "message": "That look-up is no longer known.", "result": None}
            return {**state, "request": request}

    def _run_lookup(self, request: str, work: Callable[[FmClient], Any]) -> None:
        try:
            client = FmClient(self._config.effective_settings(), self._auth)
            state = {"pending": False, "ok": True, "message": "", "result": work(client)}
        except Exception as exc:  # shown in the panel, never raised into a thread nobody watches
            log.exception("Look-up %s failed", request)
            state = {"pending": False, "ok": False, "message": str(exc) or type(exc).__name__, "result": None}
        with self._lock:
            self._lookups[request] = state

    def _status(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """The page's poll: still looking (``pending``), done (``ok`` with ``view``) or failed (``message``)."""
        with self._lock:
            return dict(self._state)

    def open_selected(self) -> None:
        """Show the item of the selected component, or of the open design when nothing is selected. UI thread."""
        number = _selected_part_number()
        if not number:
            self._ui.messageBox("Select a component that has a part number, or open a design that has one.", ITEM_COMMAND_NAME)
            return
        self._number = number
        self._start()
        self._host.show()
        self._host.send("item_changed")   # an open page starts polling again

    def _refresh(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """Read the item shown again (the page's Refresh button)."""
        if self._number:
            self._start()
        return self._status({})

    def _open_attachment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Download one of the item's files and open it with the program Windows (or macOS) uses for it."""
        ids = [str(payload.get(k) or "") for k in ("workspace_id", "item_id", "attachment_id")]
        if not all(ids):
            raise ValueError("Which file to open was not given.")
        threading.Thread(target=self._download, args=(*ids, str(payload.get("name") or "")), daemon=True).start()
        return {"started": True}

    def _download(self, workspace_id: str, item_id: str, attachment_id: str, name: str) -> None:
        try:
            client = FmClient(self._config.effective_settings(), self._auth)
            path = AttachmentService(client).download(workspace_id, item_id, attachment_id, name)
            self._tasks.post(lambda: _open_file(path))
        except Exception as exc:  # shown to the user, never raised into a thread nobody watches
            log.exception("Could not open the attachment %s", name)
            message = f"Could not open {name}:\n{exc}"
            self._tasks.post(lambda: self._ui.messageBox(message, ITEM_COMMAND_NAME))

    def _start(self) -> None:
        with self._lock:
            seq = self._state["seq"] + 1
            self._state = _answer(seq=seq, pending=True)
        threading.Thread(target=self._load, args=(seq, self._number), daemon=True).start()

    def _load(self, seq: int, number: str) -> None:
        try:
            state = _answer(ok=True, view=self._read(number))
        except ItemNotFound as exc:   # not an error: the panel says there is no such item
            log.info("No Fusion Manage item for %s", exc.number)
            state = _answer(message=str(exc), missing=exc.number)
        except NoAccess as exc:   # not an error either: the panel says so, in place of the item
            log.info("No permission to view the items workspace")
            state = _answer(message=str(exc), denied=str(exc))
        except Exception as exc:  # shown in the panel, never raised into a thread nobody watches
            log.exception("Could not read the Fusion Manage item")
            state = _answer(message=str(exc) or type(exc).__name__)
        with self._lock:
            if self._state["seq"] == seq:   # a newer open replaces this one
                self._state.update(state)

    def _read(self, number: str) -> Dict[str, Any]:
        problem = self._config.items_setup_problem()   # the ribbon greys the command out too; this covers the other ways in
        if problem:
            raise ValueError(f"{problem} Complete it in Preferences.")
        cfg = self._config.config.workspaces.get(ITEMS_KIND)
        client = FmClient(self._config.effective_settings(), self._auth)
        try:
            held = granted_permissions(client, cfg.workspace_id)
        except FmApiError as exc:
            if exc.status in (401, 403):
                raise NoAccess() from exc
            raise ValueError(f"Could not check your permissions in Fusion Manage: {exc}") from exc
        if VIEW_ITEMS not in held:   # nothing else is looked at: no access overrides everything
            raise NoAccess()
        try:
            hits = ItemService(client).search(cfg.workspace_id, number)
        except (FmApiError, AuthError) as exc:
            raise ValueError(f"Fusion Manage search failed: {exc}") from exc
        if not hits:
            raise ItemNotFound(number)
        if len(hits) > 1:
            log.warning("Item number %s matches %d items; showing the first", number, len(hits))
        return ItemViewService(client).read(cfg.workspace_id, hits[0]["id"], held)


LINE_ID = "MfgToFm_MenuLine"


class _MenuHandler(adsk.core.MarkingMenuEventHandler):
    """Adds the commands to the right-click menu when a component is selected, under one line."""

    def __init__(self, command_ids: Sequence[str]) -> None:
        super().__init__()
        self._command_ids = list(command_ids)

    def notify(self, args) -> None:
        try:
            event = adsk.core.MarkingMenuEventArgs.cast(args)
            if not any(_component_of(e) is not None for e in event.selectedEntities):
                return
            commands = adsk.core.Application.get().userInterface.commandDefinitions
            controls = event.linearMarkingMenu.controls
            if controls.itemById(LINE_ID) is None and controls.itemById(self._command_ids[0]) is None:
                controls.addSeparator(LINE_ID)   # one line above the group, none between its entries
            for command_id in self._command_ids:
                definition = commands.itemById(command_id)
                if definition and controls.itemById(command_id) is None:
                    controls.addCommand(definition)
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
        self._handler = _MenuHandler([c.command_id for c in self._commands])
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

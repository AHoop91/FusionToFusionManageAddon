"""Show a Fusion Manage item in a palette inside Fusion (the Item panel).

The item is found by item number alone: the item number of the selected component (or of the open
design when nothing is selected), read from the Data Model, is searched in the configured items workspace.
A component with no item number has not been published, so it is refused. It can be opened from
the ribbon or from the right-click menu of a selected component in the browser or canvas.

The page (``web/item``) is drawn by the add-in from the item's sections and fields, not by Fusion
Manage's web UI, so it needs no separate sign-in. Finding and reading the item call Fusion Manage, so
they run on a worker thread; the page polls ``get_item_view`` for the answer.
"""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
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
from ..fm.items import ItemService, pick_hit
from ..fm.permissions import VIEW_ITEMS, granted as granted_permissions
from ..fm.where_used import WhereUsedService
from . import drawing_source
from .attachment_upload import AttachmentUpload, UploadJob
from .item_numbers import DesignRef, ItemNumbers, NoItemNumber, Subject, active_design_ref, design_ref
from .message_bridge import MessageBridge
from .palette_host import PaletteHost
from .ribbon import RibbonCommand, define_command
from .ui_thread import UiThread
from .upload_jobs import DRAWING_JOB, STEP_JOB, pick

log = get_logger("item_panel")

LINE_ID = "MfgToFm_MenuLine"   # the line above the add-in's entries in the right-click menu
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
    """The component an entity of the selection belongs to: the component or occurrence itself, else the one holding the body, face, sketch or feature."""
    try:
        occurrence = adsk.fusion.Occurrence.cast(entity)
        if occurrence is not None:
            return occurrence.component
        component = adsk.fusion.Component.cast(entity)
    except (TypeError, RuntimeError):   # an object this API has no type for, such as the top of a drawing's tree
        return None
    if component is not None:
        return component
    for hop in (lambda e: e.assemblyContext.component if e.assemblyContext else None,   # a body or face seen through an occurrence
                lambda e: e.parentComponent,                                          # a body, sketch, feature or joint
                lambda e: e.body.parentComponent):                                    # a face, edge or vertex
        try:
            found = hop(entity)
        except (AttributeError, RuntimeError):
            continue
        if found is not None:
            return found
    return None


_menu_selection: List[Any] = []   # what was selected when the right-click menu last opened: choosing an entry may have cleared the selection by then


def _selected_component_number(entities: Any) -> str:
    """Part number of the first component the entities belong to ("" when none does, or it has no number)."""
    for entity in entities:
        component = _component_of(entity)
        if component is not None:
            return str(component.partNumber or "").strip()
    return ""


def _active_selection() -> List[Any]:
    selections = adsk.core.Application.get().userInterface.activeSelections
    return [selections.item(index).entity for index in range(selections.count)]


def _selected_part_number(from_menu: bool = False) -> str:
    """Part number of the selected component, else of the open design ("" if neither has one). In a drawing the same: a component
    of the tree gives its own number, and the top of the tree (or nothing) the number of the design the drawing shows, which is
    "" until that has loaded. ``from_menu`` reads what was selected when the right-click menu opened. Runs on the UI thread."""
    number = _selected_component_number(_menu_selection if from_menu else _active_selection())
    if number:
        return number
    if drawing_source.active_drawing() is not None:
        return drawing_source.top_level_number()[0]
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    return str(design.rootComponent.partNumber or "").strip() if design is not None else ""


def _active_ref() -> DesignRef:
    """The Data Model reference of the open design, or of the design the open drawing shows. UI thread."""
    if drawing_source.active_drawing() is not None:
        return design_ref(drawing_source.referenced_design())
    return active_design_ref()


def _open_file(path: str) -> None:
    """Open a file with its default program; a program or script is not run, its folder is shown instead."""
    if os.path.splitext(path)[1].lower() in RUNNABLE:
        path = os.path.dirname(path)
    if hasattr(os, "startfile"):
        os.startfile(path)   # Windows
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class _SelectionHandler(adsk.core.ActiveSelectionEventHandler):
    """Tells the panel when the selection changes."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        super().__init__()
        self._on_change = on_change

    def notify(self, args) -> None:
        try:
            self._on_change()
        except Exception:  # noqa: BLE001 - boundary to Fusion, must not raise
            log.exception("Could not follow the selection")


class ItemPanel:
    """Finds an item by number and shows it in the item palette."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, host: PaletteHost, bridge: MessageBridge,
                 config: ConfigService, auth: AuthService, progress: PaletteHost) -> None:
        self._ui = ui
        self._uploads = AttachmentUpload(ui, tasks, host, progress, config, auth, self._reload)
        self._tasks = tasks
        self._host = host
        self._config = config
        self._auth = auth
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = _answer(seq=0)
        self._numbers = ItemNumbers(config, auth)
        self._number = ""   # the item number the panel shows, for Refresh
        self._part = ""   # the part number Fusion gives that component
        self._selection_handler = _SelectionHandler(self._follow_selection)   # kept, or Fusion drops it
        ui.activeSelectionChanged.add(self._selection_handler)
        bridge.register("upload_status", lambda _payload: self._uploads.status())
        bridge.register("upload_context", self._upload_context)
        bridge.register("upload_drawing", self._upload_drawing)
        bridge.register("get_item_view", self._status)
        bridge.register("refresh_item_view", self._refresh)
        bridge.register("open_attachment", self._open_attachment)
        bridge.register("add_step_file", self._add_step_file)
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
        self._find(_selected_part_number(), lambda subject: self._open(subject))

    def _follow_selection(self) -> None:
        """While the panel is open, show the item of a component just selected. A selection with no component leaves the panel as it is."""
        if not self._host.visible:
            return
        number = _selected_component_number(_active_selection())
        if number and number != self._part:
            self._find(number, lambda subject: self._open(subject, show=False), quiet=True)   # it is open already

    def _find(self, part_number: str, then: Callable[[Subject], None], quiet: bool = False) -> None:
        """Read the item number of the component with ``part_number`` from the Data Model (a worker thread), then call ``then`` with it on the
        UI thread. A component with no item number is not published: the user is told (``quiet`` leaves it at the log). UI thread."""
        if not self._has_number(part_number, quiet):
            return
        ref = _active_ref()

        def work() -> None:
            self._warm()   # the workspace's layouts are read while the Data Model answers
            try:
                subject = self._numbers.resolve(ref, part_number)
            except Exception as exc:  # shown to the user, never raised into a thread nobody watches
                if isinstance(exc, NoItemNumber):
                    log.info("No item number for %s: %s", part_number, exc)
                else:
                    log.exception("Could not read the item number of %s", part_number)
                if not quiet:
                    message = str(exc) or type(exc).__name__
                    self._tasks.post(lambda: self._ui.messageBox(message, ITEM_COMMAND_NAME))
                return
            self._tasks.post(lambda: then(subject))

        threading.Thread(target=work, daemon=True).start()

    def dispose(self) -> None:
        try:
            self._ui.activeSelectionChanged.remove(self._selection_handler)
        except RuntimeError:
            pass

    def open_from_menu(self) -> None:
        """Show the item of the component the right-click menu was opened on. UI thread."""
        self._find(_selected_part_number(from_menu=True), lambda subject: self._open(subject))

    def _open(self, subject: Subject, show: bool = True) -> None:
        self._number = subject.item_number
        self._part = subject.part_number
        self._start()
        if show:
            self._host.show()
        self._host.send("item_changed", json.dumps({"item_tab": show}))   # an open page starts polling again; a panel just opened starts on the Item tab

    def _warm(self) -> None:
        """Read what the Items workspace shares between its items, ahead of the item (best effort: ``_read`` reports a real failure)."""
        try:
            cfg = self._config.config.workspaces.get(ITEMS_KIND)
            if cfg and cfg.workspace_id and not self._config.items_setup_problem():
                threading.Thread(target=ItemViewService(FmClient(self._config.effective_settings(), self._auth)).prepare,
                                 args=(cfg.workspace_id,), daemon=True).start()
        except Exception:  # noqa: BLE001 - only an optimisation
            log.debug("Could not prepare the Items workspace", exc_info=True)

    def _has_number(self, number: str, quiet: bool = False) -> bool:
        """Whether ``number`` (a part number) names a component to look up; when not, say what to select."""
        if not number and not quiet:
            self._ui.messageBox("Select a component that has a part number, or open a design that has one.", ITEM_COMMAND_NAME)
        return bool(number)

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

    def _add_step_file(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open design as the STEP file of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(STEP_JOB, payload)

    def _upload_drawing(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open drawing as the PDF of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(DRAWING_JOB, payload)

    def _upload_for_item(self, job: UploadJob, payload: Dict[str, Any]) -> Dict[str, Any]:
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        if not self._number:
            raise ValueError("No item is shown.")
        pick(_active_selection())
        return self._uploads.from_panel(job, workspace_id, item_id, Subject(self._number, self._part))

    def _upload_context(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the Actions menu uploads for the open document: the STEP file of a design, the PDF of a drawing, else nothing (``action`` is "")."""
        if drawing_source.active_drawing() is not None:
            return {"action": "upload_drawing", "label": "Upload Drawing Representation", "ext": ".pdf", "ready": bool(drawing_source.cached_number())}
        if adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is not None:
            return {"action": "add_step_file", "label": "Upload STEP File", "ext": ".step", "ready": True}
        return {"action": ""}   # neither a design nor a drawing is open: nothing to offer

    def upload_selected_step(self) -> None:
        """Upload the open design as the STEP file of the item of the selected component (the right-click entry). UI thread."""
        number = _selected_part_number(from_menu=True)
        if self._has_number(number):
            pick(_menu_selection)
            self._find(number, lambda subject: self._uploads.from_number(STEP_JOB, subject))

    def upload_drawing(self) -> None:
        """Upload the open drawing as the PDF of the item of the design it shows (the ribbon button). UI thread."""
        number, reason = drawing_source.top_level_number()
        if not number:
            self._ui.messageBox(f"The drawing is not ready yet:\n{reason}", ITEM_COMMAND_NAME)
            return
        self._find(number, lambda subject: self._uploads.from_number(DRAWING_JOB, subject))

    def _reload(self) -> None:
        """Read the item again (an upload changes its tab counts) and tell the page. UI thread."""
        if self._number:
            self._start()
            self._host.send("item_changed")

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
        with ThreadPoolExecutor(max_workers=1) as pool:
            searching = pool.submit(ItemService(client).search, cfg.workspace_id, number)   # asked while the permissions are checked
            try:
                held = granted_permissions(client, cfg.workspace_id)
            except FmApiError as exc:
                if exc.status in (401, 403):
                    raise NoAccess() from exc
                raise ValueError(f"Could not check your permissions in Fusion Manage: {exc}") from exc
            if VIEW_ITEMS not in held:   # nothing else is looked at: no access overrides everything
                raise NoAccess()
            try:
                hits = searching.result()
            except (FmApiError, AuthError) as exc:
                raise ValueError(f"Fusion Manage search failed: {exc}") from exc
        if not hits:
            raise ItemNotFound(number)
        if len(hits) > 1:
            log.warning("Item number %s matches %d items; showing the first", number, len(hits))
        return ItemViewService(client).read(cfg.workspace_id, pick_hit(hits, number)["id"], held)


def _selects_root(entities: Any) -> bool:
    """Whether the root component of the open design is among the selected entities."""
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if design is None:
        return False
    root = design.rootComponent.entityToken
    for entity in entities:
        component = adsk.fusion.Component.cast(entity)   # the component itself, not a body or occurrence inside it
        if component is not None and component.entityToken == root:
            return True
    return False


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
            event = adsk.core.MarkingMenuEventArgs.cast(args)
            entities = list(event.selectedEntities)
            _menu_selection[:] = entities
            context = "drawing" if drawing_source.active_drawing() is not None else "design"
            if context == "drawing":
                if not entities:
                    return
            elif not any(_component_of(e) is not None for e in entities):
                return
            definitions = adsk.core.Application.get().userInterface.commandDefinitions
            controls = event.linearMarkingMenu.controls
            is_root = drawing_source.selects_top_level(entities) if context == "drawing" else _selects_root(entities)
            if controls.itemById(LINE_ID) is None and controls.itemById(self._commands[0].command_id) is None:
                controls.addSeparator(LINE_ID)   # one line above the group, none between its entries
            for command in self._commands:
                shown = controls.itemById(command.command_id)
                if (command.context and command.context != context) or (command.root_only and not is_root):
                    if shown is not None:   # left over from the last time the menu opened
                        shown.deleteMe()
                    continue
                definition = definitions.itemById(command.command_id)
                if definition and shown is None:
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

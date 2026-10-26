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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..auth.errors import AuthError
from ..config.config_service import ConfigService
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID
from ..core.cancel import ADDIN, Cancelled, CancelToken, TokenSlot
from ..core.constants import ITEM_COMMAND_NAME
from ..core.logging_setup import get_logger
from ..fm.attachments import AttachmentService
from ..fm.bom_view import BomViewService
from ..fm.associated_workflows import AssociatedWorkflowService
from ..fm.change_log import ChangeLogService
from ..fm.client import FmApiError, FmClient
from ..fm.item_view import ItemViewService
from ..fm.items import SEARCH_LIMIT, ItemChoices, ItemService
from ..fm.permissions import VIEW_ITEMS, granted as granted_permissions
from ..fm.tabs import TabService
from ..fm.ttl_cache import TtlCache
from ..fm.where_used import WhereUsedService
from ..fusion_mfg.graphql_client import MfgGraphQlClient
from ..publish.writer import safe_name
from ..sync.up_to_date import UNAVAILABLE, ShownItem, check_bom, check_properties
from . import drawing_source
from .attachment_upload import AttachmentUpload, UploadJob
from .design_history import saved_state
from .export_freshness import STALE, UNSAVED, compare as compare_freshness
from .export_options import FORMATS
from .item_numbers import DesignRef, ItemNumbers, NoItemNumber, Subject, active_design_ref, design_ref
from .message_bridge import MessageBridge
from .palette_host import PaletteHost
from .ribbon import RibbonCommand, define_command
from .ui_thread import UiThread
from .upload_jobs import DRAWING_JOB, DWG_JOB, DXF_JOB, STEP_JOB, export_job, pick

log = get_logger("item_panel")

LINE_ID = "MfgToFm_MenuLine"   # the line above the add-in's entries in the right-click menu
SAVED_STATE_SECONDS = 30   # how long when a document was last saved is kept for the Files tab (see ``_saved_source``)
LOOKUPS_KEPT = 200   # answers held for the page to read before the oldest finished ones are dropped


class ItemNotFound(Exception):
    """No item in the workspace has this item number."""

    def __init__(self, number: str) -> None:
        super().__init__(f"No item exists for {number}.")
        self.number = number


class SeveralItems(Exception):
    """Several items share this item number and the user has not said which one is meant. ``candidates`` are ``{"id", "descriptor"}``."""

    def __init__(self, number: str, candidates: List[Dict[str, str]]) -> None:
        super().__init__(f"{len(candidates)} Fusion Manage items match {number}. Choose one.")
        self.number = number
        self.candidates = candidates


class NoAccess(Exception):
    """The user may not view the Items workspace."""

    def __init__(self) -> None:
        super().__init__(f"Insufficient permissions to view the {KINDS_BY_ID[ITEMS_KIND].title} workspace.")


def _answer(**changes: Any) -> Dict[str, Any]:
    """An answer of the page's poll: nothing found yet, with ``changes`` (``missing`` is an item number with no item, ``denied`` a message,
    ``choose`` the items to pick from when several share the item number ``choose_number``)."""
    return {"pending": False, "ok": False, "message": "", "view": None, "missing": "", "denied": "", "choose": [], "choose_number": "", "choose_capped": False, **changes}


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
                 config: ConfigService, auth: AuthService, progress: PaletteHost, show_publish: Callable[[], None]) -> None:
        self._ui = ui
        self._show_publish = show_publish
        self._choices = ItemChoices()   # the item picked where several share a number; the uploads use it too, so they agree with the panel
        self._uploads = AttachmentUpload(ui, tasks, host, progress, config, auth, self._reload,
                                         lambda status: bridge.push("upload_status", status), self._choices)   # the pages are told how far it has got
        self._tasks = tasks
        self._host = host
        self._config = config
        self._auth = auth
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = _answer(seq=0)
        self._numbers = ItemNumbers(config, auth)
        self._saved = TtlCache(SAVED_STATE_SECONDS)   # when the document was last saved, by (document, modified, part number)
        self._export_read = TtlCache()   # what Fusion says of what the Export window exports (its design reference, when it was saved), read once per window
        self._number = ""   # the item number the panel shows, for Refresh
        self._part = ""   # the part number Fusion gives that component
        self._selection_handler = _SelectionHandler(self._follow_selection)   # kept, or Fusion drops it
        ui.activeSelectionChanged.add(self._selection_handler)
        bridge.register("upload_status", lambda _payload: self._uploads.status())
        bridge.register("upload_context", self._upload_context)
        bridge.register("upload_drawing", self._upload_drawing)
        bridge.register("upload_dwg", self._upload_dwg)
        bridge.register("upload_dxf", self._upload_dxf)
        bridge.register("open_publish", self._open_publish)
        bridge.register("files_freshness", self._files_freshness)
        bridge.register("get_item_view", self._status)
        bridge.register("refresh_item_view", self._refresh)
        bridge.register("choose_item", self._choose_item)
        bridge.register("add_step_file", self._add_step_file)
        bridge.register("where_used_load", self._where_used_load)
        bridge.register("where_used_result", self._lookup_result)
        bridge.register("files_load", self._files_load)
        bridge.register("files_result", self._lookup_result)
        bridge.register("workflows_load", self._workflows_load)
        bridge.register("workflows_result", self._lookup_result)
        bridge.register("bom_load", self._bom_load)
        bridge.register("bom_result", self._lookup_result)
        bridge.register("changelog_load", self._changelog_load)
        bridge.register("changelog_result", self._lookup_result)
        bridge.register("sync_check_load", lambda payload: self._design_check(payload, check_properties, "sync_check_result"))   # whether the item matches the open design: its mapped fields
        bridge.register("sync_check_result", self._lookup_result)
        bridge.register("bom_check_load", lambda payload: self._design_check(payload, check_bom, "bom_check_result"))   # whether its Bill of Materials does
        bridge.register("bom_check_result", self._lookup_result)
        bridge.register("tab_counts_load", self._tab_counts_load)
        bridge.register("tab_counts_result", self._lookup_result)
        self._lookups: Dict[str, Dict[str, Any]] = {}   # request id (from the page) -> its answer
        # What is read for the item shown ends when it is left (another item, the panel hidden or the add-in stopped); see ``core.cancel``.
        self._session = TokenSlot(lambda: ADDIN, "the reads of the item panel")
        self._item_read = TokenSlot(lambda: self._session.token, "the read of the item")   # the read of the item itself
        self._follow = TokenSlot(lambda: self._session.token, "finding the item of the selection")   # of a component just selected
        self._export = TokenSlot(lambda: ADDIN, "the Export window's look at the attached files")
        self._tokens: Dict[str, CancelToken] = {}   # request id -> the token of a look-up still running
        bridge.register("lookup_cancel", self._cancel_lookups)

    def _new_session(self) -> None:
        """Another item is shown: end what was being read for the last one."""
        self._session.replace()

    def _cancel_lookups(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """End the look-ups the page names (``requests``: the ids it gave): the tab they were for was left."""
        with self._lock:
            tokens = [self._tokens[r] for r in map(str, payload.get("requests") or []) if r in self._tokens]
        for token in tokens:
            token.cancel()
        return {"cancelled": len(tokens)}

    def _where_used_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the parents of an item (or of one of those parents, given its ``up`` link); the answer is pushed to the page."""
        workspace_id, item_id, up = self._workspace_id(payload), str(payload.get("item_id") or ""), str(payload.get("up") or "")
        return self._lookup(payload, lambda client: WhereUsedService(client).read(workspace_id, item_id, up), "where_used_result")

    def _files_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the item's files; the answer is pushed to the page."""
        workspace_id, item_id, item_urn = self._workspace_id(payload), str(payload.get("item_id") or ""), str(payload.get("item_urn") or "")
        return self._lookup(payload, lambda client: AttachmentService(client).files(workspace_id, item_id, item_urn), "files_result")

    def _workflows_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the associated workflows that reference the item; the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        return self._lookup(payload, lambda client: AssociatedWorkflowService(client).read(workspace_id, item_id), "workflows_result")

    def _bom_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the item's bill of materials; the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        view_id, flat = str(payload.get("view_id") or ""), bool(payload.get("flat"))
        return self._lookup(payload, lambda client: BomViewService(client).read(workspace_id, item_id, view_id, flat), "bom_result")

    def _changelog_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading one page of the item's change log (from ``offset``); the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        offset = int(payload.get("offset") or 0)
        return self._lookup(payload, lambda client: ChangeLogService(client).read(workspace_id, item_id, offset), "changelog_result")

    def _tab_counts_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading how many entries each tab of the item holds now (a tab's Refresh button); the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        return self._lookup(payload, lambda client: TabService(client).counts(workspace_id, item_id), "tab_counts_result")

    def _design_check(self, payload: Dict[str, Any], check: Callable[[ShownItem], Dict[str, Any]], result_action: str) -> Dict[str, Any]:
        """Run ``check`` (``sync.up_to_date``) of the item shown against the open design on a worker thread, as a look-up whose answer is pushed to the page. UI thread."""
        self._workspace_id(payload)   # checks the page said which item
        item_id = str(payload.get("item_id") or "")
        ref, number = _active_ref(), self._number

        def work(fm: FmClient) -> Dict[str, Any]:
            try:
                ref_found = self._numbers.model_of(ref, fm.cancel)
            except NoItemNumber:   # no saved design is open
                return {"state": UNAVAILABLE}
            mfg = MfgGraphQlClient(self._config.effective_settings(), self._auth, fm.cancel)
            cfg = self._config.config.workspaces.get(ITEMS_KIND)
            return check(ShownItem(self._numbers.reads, mfg, fm, cfg, ref_found.model_id, ref_found.time, number, item_id))
        return self._lookup(payload, work, result_action)

    @staticmethod
    def _workspace_id(payload: Dict[str, Any]) -> str:
        """The workspace id of a look-up (the item id is checked with it)."""
        workspace_id, item_id = str(payload.get("workspace_id") or ""), str(payload.get("item_id") or "")
        if not (str(payload.get("request") or "") and workspace_id and item_id):
            raise ValueError("Which item to look up was not given.")
        return workspace_id

    def _lookup(self, payload: Dict[str, Any], work: Callable[[FmClient], Any], result_action: str) -> Dict[str, Any]:
        """Run ``work`` on a worker thread. The answer is pushed to the page as ``result_action`` when it is done; the page also asks for it
        (by the request id it gave) every so often, in case the push is missed."""
        request = str(payload["request"])
        with self._lock:
            if len(self._lookups) > LOOKUPS_KEPT:   # the page has long read the old answers
                for key in [k for k, v in self._lookups.items() if not v["pending"]][:LOOKUPS_KEPT // 2]:
                    del self._lookups[key]
            self._lookups[request] = {"pending": True, "ok": False, "message": "", "result": None}
            token = self._tokens[request] = self._session.token.child(f"look-up {request}")
        threading.Thread(target=self._run_lookup, args=(request, work, token, result_action), daemon=True).start()
        return {"started": True}

    def _lookup_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = str(payload.get("request") or "")
        with self._lock:
            state = self._lookups.get(request) or {"pending": False, "ok": False, "message": "That look-up is no longer known.", "result": None}
            return {**state, "request": request}

    def _run_lookup(self, request: str, work: Callable[[FmClient], Any], token: CancelToken, result_action: str) -> None:
        try:
            client = FmClient(self._config.effective_settings(), self._auth, token)
            state = {"pending": False, "ok": True, "message": "", "result": work(client)}
            token.check()   # cancelled just as it finished: the page has moved on
        except Cancelled:   # not a failure: the tab or the item was left, and the page no longer waits for this
            log.info("Look-up %s was cancelled", request)
            state = {"pending": False, "ok": False, "cancelled": True, "message": "", "result": None}
        except Exception as exc:  # shown in the panel, never raised into a thread nobody watches
            log.exception("Look-up %s failed", request)
            state = {"pending": False, "ok": False, "message": str(exc) or type(exc).__name__, "result": None}
        with self._lock:
            self._lookups[request] = state
            self._tokens.pop(request, None)
        self._tell_page(result_action, {**state, "request": request})

    def _tell_page(self, action: str, result: Dict[str, Any]) -> None:
        """Push ``result`` to the Item page as ``action``, in the envelope of a reply, from any thread (the send is done on Fusion's thread).
        Only this page is told: a Bill of Materials is not for the other panels."""
        data = json.dumps({"ok": True, "result": result, "error": None})
        self._tasks.post(lambda: self._host.send(action, data))

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
            self._find(number, lambda subject: self._open(subject, show=False), quiet=True, cancel=self._follow.replace())   # it is open already; a find for the last selection still going is not wanted

    def _find(self, part_number: str, then: Callable[[Subject], None], quiet: bool = False, fail: Optional[Callable[[str], None]] = None,
              cancel: Optional[CancelToken] = None) -> None:
        """Read the item number of the component with ``part_number`` from the Data Model (a worker thread), then call ``then`` with it on the
        UI thread. A component with no item number is not published: the user is told (``quiet`` leaves it at the log; ``fail`` is
        given the reason instead of a message box showing it). UI thread."""
        if not self._has_number(part_number, quiet):
            return
        ref = _active_ref()

        def work() -> None:
            self._warm()   # the workspace's layouts are read while the Data Model answers
            try:
                subject = self._numbers.resolve(ref, part_number, cancel)
            except Cancelled:   # a newer selection replaced this one
                return
            except Exception as exc:  # shown to the user, never raised into a thread nobody watches
                if isinstance(exc, NoItemNumber):
                    log.info("No item number for %s: %s", part_number, exc)
                else:
                    log.exception("Could not read the item number of %s", part_number)
                if not quiet:
                    message = str(exc) or type(exc).__name__
                    self._tasks.post(lambda: fail(message) if fail else self._ui.messageBox(message, ITEM_COMMAND_NAME))
                return
            self._tasks.post(lambda: then(subject))

        threading.Thread(target=work, daemon=True).start()

    def dispose(self) -> None:
        self._session.cancel()
        self._export.cancel()
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
        self._new_session()   # what was being read for the item shown before is not wanted
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
                                 args=(cfg.workspace_id,), daemon=True).start()   # on the add-in's token: what the next item reads too
        except Exception:  # noqa: BLE001 - only an optimisation
            log.debug("Could not prepare the Items workspace", exc_info=True)

    def _has_number(self, number: str, quiet: bool = False) -> bool:
        """Whether ``number`` (a part number) names a component to look up; when not, say what to select."""
        if not number and not quiet:
            self._ui.messageBox("Select a component that has a part number, or open a design that has one.", ITEM_COMMAND_NAME)
        return bool(number)

    def _choose_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Remember which of the items that share the number is meant (``item_id``; empty to be asked again), and read the item. UI thread."""
        cfg = self._config.config.workspaces.get(ITEMS_KIND)
        if not (self._number and cfg and cfg.workspace_id):
            raise ValueError("No item is shown.")
        self._choices.set(cfg.workspace_id, self._number, str(payload.get("item_id") or ""))
        self._start()
        self._host.send("item_changed")
        return {"chosen": True}

    def _refresh(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """Read the item shown again (the page's Refresh button)."""
        if self._number:
            self._start()
        return self._status({})

    def _add_step_file(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open design as the STEP file of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(STEP_JOB, payload)

    def _upload_drawing(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open drawing as the PDF of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(DRAWING_JOB, payload)

    def _upload_dwg(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open drawing as the DWG file of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(DWG_JOB, payload)

    def _upload_dxf(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open drawing as the DXF file of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(DXF_JOB, payload)

    def _open_publish(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open the Publish panel (Republish, or Publish for an item not yet in Fusion Manage) and close this one. A design is published, not a
        drawing. UI thread."""
        if drawing_source.active_drawing() is not None:
            return {"opened": False, "message": "Open the design to publish it: a drawing is not published."}
        self._show_publish()
        self._host.hide()
        return {"opened": True}

    def _saved_source(self) -> Dict[str, Any]:
        """When the document of the item shown was last saved (``design_history.saved_state``), kept for a short while: it reads the document's
        version history, which holds Fusion's thread (it needs Fusion's objects, so it cannot move to a worker). Saving, or changing the document
        after a save, is a different key, so a change is never missed. UI thread."""
        document = adsk.core.Application.get().activeDocument
        key = (document.name if document is not None else "", bool(document and document.isModified), self._part)
        return self._saved.get(key) or self._saved.put(key, saved_state(self._part, _active_selection()))

    def _files_freshness(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Which attached files are older than the latest save of the open document (the Files tab's Out of Date): the STEP file of a design, the
        PDF, DWG and DXF of a drawing, by the names an export gives them. Of the ``files`` the page sends (each a ``name`` and when it was
        ``updated``) it answers ``stale``: name -> why. The same comparison as the Export window's (``export_freshness.compare``). UI thread."""
        if drawing_source.active_drawing() is not None:
            extensions = (".pdf", ".dwg", ".dxf")
        elif adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is not None:
            extensions = (".step",)
        else:
            return {"stale": {}}
        base = safe_name(self._number)
        expected = {base + extension for extension in extensions}
        attached = {str(f.get("name")): f.get("updated") for f in payload.get("files") or [] if isinstance(f, dict) and f.get("name") in expected}
        if not (self._number and attached):
            return {"stale": {}}
        source = self._saved_source()
        stale = {}
        for name, updated in attached.items():
            found = compare_freshness(updated, source)
            if found["state"] in (STALE, UNSAVED):   # saved since it was uploaded, or changed since the last save: the file does not show the open document
                stale[name] = found["message"]
        return {"stale": stale}

    def _upload_for_item(self, job: UploadJob, payload: Dict[str, Any]) -> Dict[str, Any]:
        workspace_id, item_id = self._workspace_id(payload), str(payload.get("item_id") or "")
        if not self._number:
            raise ValueError("No item is shown.")
        pick(_active_selection())
        return self._uploads.from_panel(job, workspace_id, item_id, Subject(self._number, self._part))

    def _upload_context(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the Actions menu uploads for the open document, as ``actions``: the STEP file of a design, the PDF, DWG and DXF of a
        drawing, else nothing (an empty list). ``publish`` says whether Republish is offered: for a design only."""
        if drawing_source.active_drawing() is not None:
            ready = bool(drawing_source.cached_number())
            return {"publish": False, "actions": [{"action": "upload_drawing", "label": "Export PDF", "ext": ".pdf", "ready": ready},
                                {"action": "upload_dwg", "label": "Export DWG", "ext": ".dwg", "ready": ready},
                                {"action": "upload_dxf", "label": "Export DXF", "ext": ".dxf", "ready": ready}]}
        if adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is not None:
            return {"publish": True, "actions": [{"action": "add_step_file", "label": "Export STEP File", "ext": ".step", "ready": True}]}
        return {"publish": False, "actions": []}   # neither a design nor a drawing is open: nothing to offer

    def upload_selected_step(self) -> None:
        """Upload the open design as the STEP file of the item of the selected component (the right-click entry). UI thread."""
        number = _selected_part_number(from_menu=True)
        if self._has_number(number):
            pick(_menu_selection)
            self._find(number, lambda subject: self._uploads.from_number(STEP_JOB, subject))

    def upload_drawing(self) -> None:
        """Upload the open drawing as the PDF of the item of the design it shows (the right-click entry). UI thread."""
        number, reason = drawing_source.top_level_number()
        if not number:
            self._ui.messageBox(f"The drawing is not ready yet:\n{reason}", ITEM_COMMAND_NAME)
            return
        self._find(number, lambda subject: self._uploads.from_number(DRAWING_JOB, subject))

    def export_target(self) -> Tuple[str, str]:
        """``(part number, "")`` of what the Export window exports: the top of the open drawing, or the selected component (else the top) of the
        open design; ``("", why not)`` when there is nothing to export yet. UI thread."""
        if drawing_source.active_drawing() is not None:
            number, reason = drawing_source.top_level_number()
            return (number, "") if number else ("", f"The drawing is not ready yet: {reason}")
        number = _selected_part_number()
        return (number, "") if number else ("", "Select a component that has a part number, or open a design that has one.")

    def export_description(self) -> str:
        """The description Fusion holds for what Export exports: the selected component of the open design (else the design's top), or the
        design a drawing shows; "" when it has none or cannot be read. UI thread."""
        try:
            if drawing_source.active_drawing() is not None:
                design = drawing_source.referenced_design()
                component = design.rootComponent if design is not None else None
            else:
                component = next((c for c in map(_component_of, _active_selection()) if c is not None), None)
                design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
                component = component or (design.rootComponent if design is not None else None)
            return str(component.description or "").strip() if component is not None else ""
        except (AttributeError, RuntimeError):
            return ""

    def _export_state(self, number: str) -> Tuple[DesignRef, Dict[str, Any]]:
        """The design reference and the last save (``design_history.saved_state``) of what Export exports, numbered ``number``. Reading them holds
        Fusion's thread, so it is done once per window, and timed in the log. UI thread."""
        document = adsk.core.Application.get().activeDocument
        key = (number, document.name if document is not None else "")
        kept = self._export_read.get(key)
        if kept:
            return kept
        began = time.monotonic()
        ref = _active_ref()
        referenced = time.monotonic()
        source = saved_state(number, _active_selection())
        log.info("Export state of %s read on Fusion's thread in %.2fs (design reference %.2fs, last saved %.2fs)", number,
                 time.monotonic() - began, referenced - began, time.monotonic() - referenced)
        return self._export_read.put(key, (ref, source))

    def warm_export_target(self, found: Callable[[str, str], None]) -> None:
        """Read the item number of what Export will export ahead of the click, on a worker thread, so that the Data Model (about two seconds
        the first time for a design) is already read, and kept, when Export is pressed. ``found(part number, item number)`` is called from the
        worker once it is known, with "" when it could not be read. A failure is left for the click to report. UI thread."""
        number, _problem = self.export_target()
        if not number:
            return
        ref = _active_ref()
        cancel = self._export.token

        def work() -> None:
            try:
                subject = self._numbers.resolve(ref, number, cancel)
            except Cancelled:   # the window was closed
                return
            except Exception as exc:  # noqa: BLE001 - only an optimisation
                log.info("Item number of %s not read ahead: %s", number, exc)
                found(number, "")   # no item number: the title is left empty
                return
            found(number, subject.item_number)
            self._uploads.warm_component(subject.item_number, cancel)

        threading.Thread(target=work, daemon=True).start()

    @property
    def export_token(self) -> CancelToken:
        """The token of what the Export window is reading now (see ``cancel_export``)."""
        return self._export.token

    def cancel_export(self) -> None:
        """End what the Export window is still reading from Fusion Manage and the Data Model (it was closed, or is opened again). UI thread."""
        self._export.replace()

    def reset_export(self) -> None:
        """Forget what was read for an earlier Export window: the document may have been saved since. UI thread."""
        self.cancel_export()   # what an earlier window was still reading is not wanted
        self._export_read.clear()
        self._numbers.forget_files()

    def export_files(self, key: str, destination: str, number: str, done: Callable[[Dict[str, Any]], None]) -> None:
        """Say what exporting the part ``number`` as the format ``key`` to ``destination`` would do to the files attached in Fusion Manage: add
        one, or make a new version of the one of that name (``AttachmentUpload.preview``). Told to ``done`` from a worker thread. UI thread."""
        if not number:
            done({"state": "unavailable", "message": "Nothing to export yet."})
            return
        ref, source = self._export_state(number)
        extension = FORMATS[key].extension
        cancel = self._export.token   # the window's: its other looks are not ended by this one, but closing it ends them all

        def work() -> None:
            try:
                item_number = self._numbers.resolve(ref, number, cancel).item_number
                done(self._uploads.preview(destination, item_number, f"{safe_name(item_number)}{extension}", source, cancel))
            except Cancelled:   # the window was closed: nobody waits for the answer
                log.info("The look at the files for the export of %s was cancelled", number)
            except Exception as exc:  # noqa: BLE001 - shown in the Export window, never raised into a thread nobody watches
                log.info("Files for the export of %s not read: %s", number, exc)
                done({"state": "unavailable", "message": str(exc)})

        threading.Thread(target=work, daemon=True).start()

    def export(self, key: str, destination: str) -> None:
        """Export the open document as the format ``key`` and attach it to the item (or the component) ``destination`` of the part
        ``export_target`` gives. The Export window follows it (``begin_in_window``), so it is told how it went, not shown a message box.
        Raises ``ValueError`` when there is nothing to export or an upload is already under way. UI thread."""
        number, problem = self.export_target()
        if not number:
            raise ValueError(problem)
        job = export_job(key)
        if not self._uploads.begin_in_window(job):
            raise ValueError("A file is already being uploaded.")
        began = time.monotonic()
        pick(_active_selection())
        self._find(number, lambda subject: self._uploads.continue_in_window(job, subject, destination), fail=self._uploads.fail_in_window)
        log.info("Export began its search after %.2fs on Fusion's thread", time.monotonic() - began)

    def _reload(self) -> None:
        """Read the item again (an upload changes its tab counts) and tell the page. UI thread."""
        if self._number:
            self._start()
            self._host.send("item_changed")

    def _start(self) -> None:
        with self._lock:
            seq = self._state["seq"] + 1
            self._state = _answer(seq=seq, pending=True)
        token = self._item_read.replace()   # the read of the item before this one, if it is still going, is not wanted
        threading.Thread(target=self._load, args=(seq, self._number, token), daemon=True).start()

    def _load(self, seq: int, number: str, token: CancelToken) -> None:
        try:
            state = _answer(ok=True, view=self._read(number, token))
        except Cancelled:   # a newer read (or another item, or the add-in stopping) replaced this one: it has nothing to say
            log.info("The read of item %s was cancelled", number)
            return
        except ItemNotFound as exc:   # not an error: the panel says there is no such item
            log.info("No Fusion Manage item for %s", exc.number)
            state = _answer(message=str(exc), missing=exc.number)
        except SeveralItems as exc:   # not an error either: the panel lists the items, and the user picks one
            log.info("%d Fusion Manage items for %s: the user is asked which", len(exc.candidates), exc.number)
            state = _answer(message=str(exc), choose=exc.candidates, choose_number=exc.number, choose_capped=len(exc.candidates) >= SEARCH_LIMIT)
        except NoAccess as exc:   # not an error either: the panel says so, in place of the item
            log.info("No permission to view the items workspace")
            state = _answer(message=str(exc), denied=str(exc))
        except Exception as exc:  # shown in the panel, never raised into a thread nobody watches
            log.exception("Could not read the Fusion Manage item")
            state = _answer(message=str(exc) or type(exc).__name__)
        with self._lock:
            if self._state["seq"] != seq:   # a newer open replaces this one
                return
            self._state.update(state)
            answer = dict(self._state)
        self._tell_page("get_item_view", answer)

    def _read(self, number: str, cancel: CancelToken) -> Dict[str, Any]:
        problem = self._config.items_setup_problem()   # the ribbon greys the command out too; this covers the other ways in
        if problem:
            raise ValueError(f"{problem} Complete it in Preferences.")
        cfg = self._config.config.workspaces.get(ITEMS_KIND)
        client = FmClient(self._config.effective_settings(), self._auth, cancel)
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
        picked, competing = self._choices.resolve(cfg.workspace_id, number, hits)
        if len(competing) > 1:
            log.info("Item number %s matches %d items: %s", number, len(competing), "; ".join(f"{h['id']} ({h['descriptor']})" for h in competing))
        if picked is None:
            raise SeveralItems(number, competing)
        view = ItemViewService(client).read(cfg.workspace_id, picked["id"], held)
        view["others"] = competing if len(competing) > 1 else []   # the page offers to choose again
        return view


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

"""Show a Fusion Manage item in a palette inside Fusion (the Item panel).

The item is found as publish finds the MBOM items of a design: the selected component (or the open design when nothing
is selected) is looked up in the Data Model, and the configured items workspace is searched for the items that carry the
lineage id and asset id of its record in the Components workspace (the ``COMPONENT_LINEAGE_URN`` and ``COMPONENT_ASSET_URN``
fields). Several are a choice for the user. A component with no item number has not been published, so it is refused. It can be opened from
the ribbon or from the right-click menu of a selected component in the browser or canvas.

The page (``web/item``) is drawn by the add-in from the item's sections and fields, not by Fusion
Manage's web UI, so it needs no separate sign-in. Finding and reading the item call Fusion Manage, so
they run on a worker thread; the page polls ``get_item_view`` for the answer.

Layer: UI (the Item page's actions: tab look-ups, item loading and reading, selection following, uploads from the Actions menu, files
freshness). The right-click menu is ``item_context_menu``, the reads of what Fusion has selected or open are ``fusion_selection``, finding
the item number of a component is ``number_finder``, and the Export window's reads and export are ``export_panel`` (the panel builds it
as ``exporter``).
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..auth.errors import AuthError
from ..config.config_service import ConfigService
from ..config.hub_context import HubContext, HubContexts
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID, kind_texts
from ..core.cancel import ADDIN, Cancelled, CancelToken, TokenSlot
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..fm.attachments import AttachmentService
from ..fm.bom_view import BomViewService
from ..fm.associated_workflows import AssociatedWorkflowService
from ..fm.change_log import ChangeLogService
from ..fm.client import FmApiError, FmClient
from ..fm.components import ComponentService
from ..fm.item_view import ItemViewService
from ..fm.mbom import MbomService
from ..fm.v3_search import ItemChoices
from ..fm.permissions import VIEW_ITEMS, granted as granted_permissions
from ..fm.tableaus import TableauService
from ..fm.tabs import TabService
from ..fm.ttl_cache import TtlCache
from ..fm.where_used import WhereUsedService
from ..fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ..publish.writer import safe_name
from ..sync.up_to_date import UNAVAILABLE, ShownItem, check_bom, check_properties
from . import drawing_source, fusion_selection
from .attachment_upload import AttachmentUpload, UploadJob
from .design_history import saved_state
from .export_freshness import STALE, UNSAVED, compare as compare_freshness
from .export_panel import ExportPanel
from .export_options import DWG, DXF, PDF
from .item_numbers import DesignRef, ItemNumbers, NoItemNumber, Subject
from .message_bridge import MessageBridge
from .number_finder import FindOptions, NumberFinder
from .palette_host import PaletteHost
from .ui_thread import UiThread
from .ui_text import item_command_name
from .upload_jobs import drawing_job, pick, step_job

log = get_logger("item_panel")

SAVED_STATE_SECONDS = 30   # how long when a document was last saved is kept for the Files tab (see ``_saved_source``)
LOOKUPS_KEPT = 200   # answers held for the page to read before the oldest finished ones are dropped


class _Lookup(NamedTuple):
    """A look-up of the page, as its worker thread runs it: ``work`` under ``token`` and ``context``, its answer pushed as ``result_action``."""

    request: str
    work: Callable[[FmClient], Any]
    token: CancelToken
    result_action: str
    context: HubContext


class ItemNotFound(Exception):
    """No item in the workspace has this item number."""

    def __init__(self, number: str) -> None:
        super().__init__(t("app.no_item_for_number", number=number))
        self.number = number


class SeveralItems(Exception):
    """Several items share this item number and the user has not said which one is meant. ``candidates`` are ``{"id", "descriptor"}``."""

    def __init__(self, number: str, candidates: List[Dict[str, str]]) -> None:
        super().__init__(t("app.items_match_choose", count=len(candidates), number=number))
        self.number = number
        self.candidates = candidates


class NoAccess(Exception):
    """The user may not view the Items workspace."""

    def __init__(self) -> None:
        super().__init__(t("app.no_view_permission", workspace=kind_texts(KINDS_BY_ID[ITEMS_KIND])[0]))


def _answer(**changes: Any) -> Dict[str, Any]:
    """An answer of the page's poll: nothing found yet, with ``changes`` (``missing`` is an item number with no item, ``denied`` a message,
    ``choose`` the items to pick from when several are made from the component whose item number is ``choose_number``). ``stamp`` is that of the hub context the
    answer was read under: the page sends it back with what it asks of what it shows (see ``ItemPanel._context_of``)."""
    return {"pending": False, "ok": False, "message": "", "view": None, "missing": "", "denied": "", "choose": [], "choose_number": "",
            "stamp": "", **changes}


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

    # Eight parameters, over the guardrail of four: each is a different collaborator the add-in's one wiring place hands over, and a bundle
    # object would only be a second spelling of the same list. It is left as it is, and its one caller (and the tests) stay as they are.
    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, host: PaletteHost, bridge: MessageBridge,
                 config: ConfigService, auth: AuthService, progress: PaletteHost, show_publish: Callable[[], None]) -> None:
        self._ui = ui
        self._show_publish = show_publish
        self._found = TtlCache(300)   # the items found for a component, by (workspace, subject): kept for the choice among them, and cleared by an open
        self._design_choices = ItemChoices()   # the item picked where several are made from the component shown; the uploads use it too, so they agree with the panel
        self._numbers = ItemNumbers()
        self._uploads = AttachmentUpload(ui, tasks, host, progress, config, auth, self._reload,
                                         lambda status: bridge.push("upload_status", status), self._design_choices,   # the pages are told how far it has got
                                         records=self._numbers.record_link)
        self._tasks = tasks
        self._host = host
        self._contexts = HubContexts(config, auth.session)
        self._auth = auth
        self._finder = NumberFinder(ui, tasks, self._contexts, self._numbers, auth)
        self.exporter = ExportPanel(self._contexts, self._numbers, self._uploads, self._finder)   # what the Export window reads and does
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = _answer(seq=0)
        self._saved = TtlCache(SAVED_STATE_SECONDS)   # when the document was last saved, by (document, modified, part number)
        self._number = ""   # the item number the panel shows, for Refresh
        self._part = ""   # the part number Fusion gives that component
        self._ref: Optional[DesignRef] = None   # where the Data Model finds that component: its record is what the item is found by
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
        bridge.register("picture_load", self._picture_load)
        bridge.register("picture_result", self._lookup_result)
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
        self._tokens: Dict[str, CancelToken] = {}   # request id -> the token of a look-up still running
        bridge.register("lookup_cancel", self._cancel_lookups)
        config.on_change(lambda: tasks.post(self._context_changed))   # from whichever thread changed them: the panel is read on Fusion's
        auth.on_session_change(lambda: tasks.post(self._context_changed))   # likewise a sign-in or a sign-out

    def _context_of(self, payload: Dict[str, Any]) -> HubContext:
        """The context a request of the page is made under: the hub and settings active now, provided they are those the item shown was read
        under (the page sends the ``stamp`` of what it shows). Raises when they are not, or cannot be read: ids read under one tenant are
        never paired with another's. UI thread."""
        context, reason = self._contexts.attempt()
        if context is None:
            raise ValueError(reason)
        wrong = context.mismatch(payload)
        if wrong:
            raise ValueError(wrong)
        return context

    def _context_changed(self) -> None:
        """The hub, the settings or the signed-in user changed: read the item shown again if it was read under others. UI thread."""
        if not (self._number and self._host.visible):
            return
        context, _reason = self._contexts.attempt()   # settings that cannot be read: the read says why
        stamp = context.stamp if context else ""
        with self._lock:
            shown = self._state["stamp"]
        if stamp != shown:
            self._reload()

    def _cancel_lookups(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """End the look-ups the page names (``requests``: the ids it gave): the tab they were for was left."""
        with self._lock:
            tokens = [self._tokens[r] for r in map(str, payload.get("requests") or []) if r in self._tokens]
        for token in tokens:
            token.cancel()
        return {"cancelled": len(tokens)}

    def _where_used_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the parents of an item (or of one of those parents, given its ``up`` link); the answer is pushed to the page."""
        workspace_id, item_id, up = self._workspace_id(payload), self._item_id(payload), str(payload.get("up") or "")
        return self._lookup(payload, lambda client: WhereUsedService(client).read(workspace_id, item_id, up), "where_used_result")

    def _picture_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading one picture of an image field of the item shown (``link`` is the one the item gave); the answer is pushed to the page."""
        workspace_id, link = self._workspace_id(payload), str(payload.get("link") or "")
        return self._lookup(payload, lambda client: TableauService(client).picture(workspace_id, link), "picture_result")

    def _files_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the item's files; the answer is pushed to the page."""
        workspace_id, item_id, item_urn = self._workspace_id(payload), self._item_id(payload), str(payload.get("item_urn") or "")
        return self._lookup(payload, lambda client: AttachmentService(client).files(workspace_id, item_id, item_urn), "files_result")

    def _workflows_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the associated workflows that reference the item; the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), self._item_id(payload)
        return self._lookup(payload, lambda client: AssociatedWorkflowService(client).read(workspace_id, item_id), "workflows_result")

    def _bom_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading the item's bill of materials; the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), self._item_id(payload)
        view_id, flat = str(payload.get("view_id") or ""), bool(payload.get("flat"))
        return self._lookup(payload, lambda client: BomViewService(client).read(workspace_id, item_id, view_id, flat), "bom_result")

    def _changelog_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading one page of the item's change log (from ``offset``); the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), self._item_id(payload)
        offset = int(payload.get("offset") or 0)
        return self._lookup(payload, lambda client: ChangeLogService(client).read(workspace_id, item_id, offset), "changelog_result")

    def _tab_counts_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start reading how many entries each tab of the item holds now (a tab's Refresh button); the answer is pushed to the page."""
        workspace_id, item_id = self._workspace_id(payload), self._item_id(payload)
        return self._lookup(payload, lambda client: TabService(client).counts(workspace_id, item_id), "tab_counts_result")

    def _design_check(self, payload: Dict[str, Any], check: Callable[[ShownItem], Dict[str, Any]], result_action: str) -> Dict[str, Any]:
        """Run ``check`` (``sync.up_to_date``) of the item shown against the open design on a worker thread, as a look-up whose answer is pushed to the page. UI thread."""
        self._workspace_id(payload)   # checks the page said which item
        context = self._lookup_context(payload, result_action)
        if context is None:
            return {"started": True}
        item_id = self._item_id(payload)
        ref, number = fusion_selection.active_ref(), self._number

        def work(fm: FmClient) -> Dict[str, Any]:
            try:
                ref_found = self._numbers.model_of(ref, fm.cancel)
            except NoItemNumber:   # no saved design is open
                return {"state": UNAVAILABLE}
            mfg = FusionGraphQlClient(fm.cancel)
            return check(ShownItem(self._numbers.reads, mfg, fm, context.cfg, ref_found.model_id, ref_found.time, number, item_id))
        return self._lookup(payload, work, result_action, context)

    @staticmethod
    def _item_id(payload: Dict[str, Any]) -> str:
        """The id of the item a request of the page is about."""
        return str(payload.get("item_id") or "")

    @classmethod
    def _workspace_id(cls, payload: Dict[str, Any]) -> str:
        """The workspace id of a look-up (the item id is checked with it)."""
        workspace_id, item_id = str(payload.get("workspace_id") or ""), cls._item_id(payload)
        if not (str(payload.get("request") or "") and workspace_id and item_id):
            raise ValueError(t("app.lookup_no_item"))
        return workspace_id

    def _lookup_context(self, payload: Dict[str, Any], result_action: str) -> Optional[HubContext]:
        """The context of a look-up (``_context_of``), or None when it cannot be taken: the look-up is then answered with why. UI thread."""
        try:
            return self._context_of(payload)
        except Exception as exc:  # noqa: BLE001 - the page is waiting for an answer to this look-up
            log.warning("Look-up refused: %s", exc)
            request = str(payload["request"])
            state = {"pending": False, "ok": False, "message": str(exc) or type(exc).__name__, "result": None}
            with self._lock:
                self._lookups[request] = state
            self._tell_page(result_action, {**state, "request": request})
            return None

    def _lookup(self, payload: Dict[str, Any], work: Callable[[FmClient], Any], result_action: str,
                context: Optional[HubContext] = None) -> Dict[str, Any]:
        """Run ``work`` on a worker thread, under ``context`` (that of the page's ``stamp``, taken here when not given). The answer is pushed
        to the page as ``result_action`` when it is done; the page also asks for it (by the request id it gave) every so often, in case the
        push is missed."""
        context = context or self._lookup_context(payload, result_action)
        if context is None:
            return {"started": True}
        request = str(payload["request"])
        with self._lock:
            if len(self._lookups) > LOOKUPS_KEPT:   # the page has long read the old answers
                for key in [k for k, v in self._lookups.items() if not v["pending"]][:LOOKUPS_KEPT // 2]:
                    del self._lookups[key]
            self._lookups[request] = {"pending": True, "ok": False, "message": "", "result": None}
            token = self._tokens[request] = self._session.token.child(f"look-up {request}")
        threading.Thread(target=self._run_lookup, args=(_Lookup(request, work, token, result_action, context),), daemon=True).start()
        return {"started": True}

    def _lookup_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The answer of the look-up the page names (``request``), as ``_lookup`` keeps it; the page asks while it has heard nothing."""
        request = str(payload.get("request") or "")
        with self._lock:
            state = self._lookups.get(request) or {"pending": False, "ok": False, "message": t("app.lookup_unknown"), "result": None}
            return {**state, "request": request}

    def _run_lookup(self, lookup: _Lookup) -> None:
        """A look-up, on its own thread: run its ``work``, keep the outcome under its request id and push it to the page."""
        request = lookup.request
        try:
            client = FmClient(lookup.context.settings, self._auth, lookup.token)
            state = {"pending": False, "ok": True, "message": "", "result": lookup.work(client)}
            lookup.token.check()   # cancelled just as it finished: the page has moved on
        except Cancelled:   # not a failure: the tab or the item was left, and the page no longer waits for this
            log.info("Look-up %s was cancelled", request)
            state = {"pending": False, "ok": False, "cancelled": True, "message": "", "result": None}
        except Exception as exc:  # shown in the panel, never raised into a thread nobody watches
            log.exception("Look-up %s failed", request)
            state = {"pending": False, "ok": False, "message": str(exc) or type(exc).__name__, "result": None}
        with self._lock:
            self._lookups[request] = state
            self._tokens.pop(request, None)
        self._tell_page(lookup.result_action, {**state, "request": request})

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
        self._open_part(fusion_selection.selected_part_number())

    def _open_part(self, part_number: str) -> None:
        """Open the panel at once, with its loading state, and find the item of ``part_number`` behind it: nothing waits for Fusion Manage or the
        Data Model before the panel shows. Why the part could not be found is the panel's answer, not a message box. A part with no number is
        refused first (the message box says what to select). UI thread."""
        if not self._finder.has_number(part_number):
            return
        seq = self._loading()
        self._finder.find(part_number, lambda subject: self._open(subject, show=False),
                          FindOptions(fail=lambda message: self._settle(seq, _answer(message=message))))

    def _loading(self) -> int:
        """Show the panel (a new one loads its page, an open one is told) in its loading state: the read number the answer will settle."""
        self._session.replace()   # what was being read for the item shown before is not wanted
        self._number, self._part, self._ref = "", "", None   # no item is shown until this one is found: a failed find must not leave the one before as the item to Refresh or upload to
        with self._lock:
            seq = self._state["seq"] + 1
            self._state = _answer(seq=seq, pending=True)
        self._host.show()
        self._host.send("item_changed", json.dumps({"item_tab": True}))   # the loading screen at once; a panel just opened starts on the Item tab
        return seq

    def _follow_selection(self) -> None:
        """While the panel is open, show the item of a component just selected. A selection with no component leaves the panel as it is."""
        if not self._host.visible:
            return
        number = fusion_selection.selected_component_number(fusion_selection.active_selection())
        if number and number != self._part:
            self._finder.find(number, lambda subject: self._open(subject, show=False), FindOptions(quiet=True, cancel=self._follow.replace()))   # it is open already; a find for the last selection still going is not wanted

    def dispose(self) -> None:
        """End everything still being read, and stop following the selection. UI thread."""
        self._session.cancel()
        self.exporter.dispose()
        try:
            self._ui.activeSelectionChanged.remove(self._selection_handler)
        except RuntimeError:
            pass

    def open_from_menu(self) -> None:
        """Show the item of the component the right-click menu was opened on. UI thread."""
        self._open_part(fusion_selection.selected_part_number(from_menu=True))

    def _open(self, subject: Subject, show: bool = True) -> None:
        """Show the item of ``subject``; ``show`` opens the palette too (not when it follows a selection while open already). UI thread."""
        self._number = subject.item_number
        self._part = subject.part_number
        self._ref = subject.ref
        self._session.replace()   # what was being read for the item shown before is not wanted (and cannot add to what is cleared next)
        self._found.clear()   # a new open looks for the items again,
        self._design_choices.forget(subject.item_number)   # and asks which is meant: a pick is for the table it was made in
        self._start()
        if show:
            self._host.show()
        self._host.send("item_changed", json.dumps({"item_tab": show}))   # an open page starts polling again; a panel just opened starts on the Item tab

    def _choose_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Remember which of the items that share the number is meant (``item_id``; empty to be asked again), and read the item. UI thread."""
        cfg = self._context_of(payload).cfg
        if not (self._number and cfg and cfg.workspace_id):
            raise ValueError(t("app.no_item_shown"))
        self._design_choices.set(cfg.workspace_id, self._number, self._item_id(payload))
        self._start()
        self._host.send("item_changed", json.dumps({"chosen": True}))   # the items are known: the page says it is loading the item, not finding it
        return {"chosen": True}

    def _refresh(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """Read the item shown again (the page's Refresh button), and the layout of its workspace with it."""
        if self._number:
            ItemViewService.forget()
            ComponentService.forget()
            self._numbers.forget_links()
            self._found.clear()
            self._start()
        return self._status({})

    def _add_step_file(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open design as the STEP file of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(step_job(), payload)

    def _upload_drawing(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open drawing as the PDF of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(drawing_job(PDF), payload)

    def _upload_dwg(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open drawing as the DWG file of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(drawing_job(DWG), payload)

    def _upload_dxf(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the open drawing as the DXF file of the item shown (the Actions menu). UI thread."""
        return self._upload_for_item(drawing_job(DXF), payload)

    def _open_publish(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open the Publish panel (Republish, or Publish for an item not yet in Fusion Manage) and close this one. A design is published, not a
        drawing. UI thread."""
        if drawing_source.active_drawing() is not None:
            return {"opened": False, "message": t("app.drawing_not_published")}
        self._show_publish()
        self._host.hide()
        return {"opened": True}

    def _saved_source(self) -> Dict[str, Any]:
        """When the document of the item shown was last saved (``design_history.saved_state``), kept for a short while: it reads the document's
        version history, which holds Fusion's thread (it needs Fusion's objects, so it cannot move to a worker). Saving, or changing the document
        after a save, is a different key, so a change is never missed. UI thread."""
        document = adsk.core.Application.get().activeDocument
        key = (document.name if document is not None else "", bool(document and document.isModified), self._part)
        return self._saved.get(key) or self._saved.put(key, saved_state(self._part, fusion_selection.active_selection()))

    def _files_freshness(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Which attached files are older than the latest save of the open document (the Files tab's Out of Date): the STEP file of a design, the
        PDF, DWG and DXF of a drawing, by the names an export gives them. Of the ``files`` the page sends (each a ``name`` and when it was
        ``updated``) it answers ``stale``: name -> why. The same comparison as the Export window's (``export_freshness.compare``). UI thread."""
        extensions = self._exported_extensions()
        if not extensions:
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

    @staticmethod
    def _exported_extensions() -> Tuple[str, ...]:
        """The extensions of the files an export of the open document attaches: the PDF, DWG and DXF of a drawing, the STEP file of a design,
        none for neither. UI thread."""
        if drawing_source.active_drawing() is not None:
            return (".pdf", ".dwg", ".dxf")
        return (".step",) if fusion_selection.open_design() is not None else ()

    def _upload_for_item(self, job: UploadJob, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start ``job`` for the item the page shows. Raises ``ValueError`` when no item is shown or the context has changed. UI thread."""
        workspace_id, item_id = self._workspace_id(payload), self._item_id(payload)
        if not self._number:
            raise ValueError(t("app.no_item_shown"))
        context = self._context_of(payload)   # the item shown was read under the settings that are active still
        pick(fusion_selection.active_selection())
        return self._uploads.from_panel(job, context, workspace_id, item_id, Subject(self._number, self._part))

    def _upload_context(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the Actions menu uploads for the open document, as ``actions``: the STEP file of a design, the PDF, DWG and DXF of a
        drawing, else nothing (an empty list). ``publish`` says whether Republish is offered: for a design only."""
        if drawing_source.active_drawing() is not None:
            ready = bool(drawing_source.cached_number())
            return {"publish": False, "actions": [{"action": "upload_drawing", "label": t("app.export_pdf_label"), "ext": ".pdf", "ready": ready},
                                {"action": "upload_dwg", "label": t("app.export_dwg_label"), "ext": ".dwg", "ready": ready},
                                {"action": "upload_dxf", "label": t("app.export_dxf_label"), "ext": ".dxf", "ready": ready}]}
        if fusion_selection.open_design() is not None:
            return {"publish": True, "actions": [{"action": "add_step_file", "label": t("app.export_step_name"), "ext": ".step", "ready": True}]}
        return {"publish": False, "actions": []}   # neither a design nor a drawing is open: nothing to offer

    def upload_selected_step(self) -> None:
        """Upload the open design as the STEP file of the item of the selected component (the right-click entry). UI thread."""
        number = fusion_selection.selected_part_number(from_menu=True)
        if self._finder.has_number(number):
            pick(fusion_selection.menu_selection)
            self._finder.find(number, lambda subject: self._uploads.from_number(step_job(), subject))

    def upload_drawing(self) -> None:
        """Upload the open drawing as the PDF of the item of the design it shows (the right-click entry). UI thread."""
        number, reason = drawing_source.top_level_number()
        if not number:
            self._ui.messageBox(t("app.drawing_not_ready_box", reason=reason), item_command_name())
            return
        self._finder.find(number, lambda subject: self._uploads.from_number(drawing_job(PDF), subject))

    def _reload(self) -> None:
        """Read the item again (an upload changes its tab counts) and tell the page. UI thread."""
        if self._number:
            self._start()
            self._host.send("item_changed")

    def _start(self) -> None:
        """Read the item shown, under the hub and settings active now. UI thread."""
        with self._lock:
            seq = self._state["seq"] + 1
            self._state = _answer(seq=seq, pending=True)
        token = self._item_read.replace()   # the read of the item before this one, if it is still going, is not wanted
        context, reason = self._contexts.attempt()
        if context is None:   # e.g. Shared Configuration that cannot be read: the panel says so
            self._settle(seq, _answer(message=reason))
            return
        threading.Thread(target=self._load, args=(seq, Subject(self._number, self._part, self._ref), token, context), daemon=True).start()

    def _load(self, seq: int, subject: Subject, token: CancelToken, context: HubContext) -> None:
        """Read the item for read number ``seq``, on a worker thread, and settle the answer: the item, or why there is none."""
        try:
            view = self._read(subject, token, context)
            view["stamp"] = context.stamp   # the page sends it with each look-up and upload for this item
            state = _answer(ok=True, view=view)
        except Cancelled:   # a newer read (or another item, or the add-in stopping) replaced this one: it has nothing to say
            log.info("The read of item %s was cancelled", subject.item_number)
            return
        except ItemNotFound as exc:   # not an error: the panel says there is no such item
            log.info("No Fusion Manage item for %s", exc.number)
            state = _answer(message=str(exc), missing=exc.number)
        except SeveralItems as exc:   # not an error either: the panel lists the items, and the user picks one
            log.info("%d Fusion Manage items for %s: the user is asked which", len(exc.candidates), exc.number)
            state = _answer(message=str(exc), choose=exc.candidates, choose_number=exc.number)
        except NoAccess as exc:   # not an error either: the panel says so, in place of the item
            log.info("No permission to view the items workspace")
            state = _answer(message=str(exc), denied=str(exc))
        except Exception as exc:  # shown in the panel, never raised into a thread nobody watches
            log.exception("Could not read the Fusion Manage item")
            state = _answer(message=str(exc) or type(exc).__name__)
        state["stamp"] = context.stamp
        self._settle(seq, state)

    def _settle(self, seq: int, state: Dict[str, Any]) -> None:
        """Keep ``state`` as the answer of read number ``seq`` and tell the page (unless a newer read has replaced it)."""
        with self._lock:
            if self._state["seq"] != seq:   # a newer open replaces this one
                return
            self._state.update(state)
            answer = dict(self._state)
        self._tell_page("get_item_view", answer)

    @staticmethod
    def _held_permissions(client: FmClient, workspace_id: str) -> Any:
        """The permissions the user holds in the Items workspace. Raises ``NoAccess`` when the user may not view it, and ``ValueError`` for what
        stops the check."""
        try:
            held = granted_permissions(client, workspace_id)
        except FmApiError as exc:
            if exc.status in (401, 403):
                raise NoAccess() from exc
            raise ValueError(t("app.permissions_check_failed", reason=exc)) from exc
        if VIEW_ITEMS not in held:   # nothing else is looked at: no access overrides everything
            raise NoAccess()
        return held

    def _items_of_component(self, client: FmClient, cfg: Any, subject: Subject, cancel: CancelToken) -> List[Dict[str, Any]]:
        """The items of the Items workspace made from the component of ``subject`` (its reference and part number), found by the lineage id and the
        asset id of its record in the Components workspace, as publish finds the MBOM items of a design. Raises ``ValueError`` for what stops
        the search: the component has no record there yet, the record has no design or asset id, or the search fails (the workspace needs the
        ``COMPONENT_LINEAGE_URN`` and ``COMPONENT_ASSET_URN`` fields). Worker thread."""
        if subject.ref is None:
            raise ValueError(t("app.no_item_shown"))
        link = self._numbers.record_link(subject.ref, subject.part_number, cancel)
        if not link:
            raise ValueError(t("data.fm_mbom_not_linked"))
        try:
            return MbomService(client).of_component(cfg.workspace_id, link, cfg.item_number_field())
        except (FmApiError, AuthError) as exc:
            raise ValueError(t("app.search_failed", reason=exc)) from exc

    def _read(self, subject: Subject, cancel: CancelToken, context: HubContext) -> Dict[str, Any]:
        """The view of the item of the component ``subject``, found by lineage and asset URN. Raises ``NoAccess``,
        ``ItemNotFound`` or ``SeveralItems`` for what the panel shows in place of an item, and ``ValueError`` for what stops the read."""
        problem = context.items_problem   # the ribbon greys the command out too; this covers the other ways in
        if problem:
            raise ValueError(t("app.complete_in_preferences", problem=problem))
        cfg = context.cfg
        client = FmClient(context.settings, self._auth, cancel)
        known = self._found.get((cfg.workspace_id, subject))   # found when the panel was opened: choosing one of them does not search again
        if known is not None:
            held, hits = self._held_permissions(client, cfg.workspace_id), known
        else:
            with ThreadPoolExecutor(max_workers=1) as pool:
                searching = pool.submit(self._items_of_component, client, cfg, subject, cancel)   # asked while the permissions are checked
                held = self._held_permissions(client, cfg.workspace_id)
                hits = searching.result()
            if hits:
                self._found.put((cfg.workspace_id, subject), hits)
        number = subject.item_number
        if not hits:
            raise ItemNotFound(number)
        picked, competing = self._design_choices.pick(cfg.workspace_id, number, hits)
        if len(competing) > 1:
            log.info("Item number %s has %d items made from its component: %s", number, len(competing), ", ".join(str(h["id"]) for h in competing))
        if picked is None:
            raise SeveralItems(number, competing)
        view = ItemViewService(client).read(cfg.workspace_id, picked["id"], held, pictures=False)   # the page draws the item first and asks for each picture after
        view["others"] = competing if len(competing) > 1 else []   # the page offers to choose again
        return view

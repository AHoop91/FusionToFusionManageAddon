"""The sections of the open design that the Publish Item panel asks for, and how each is loaded.

The panel asks for a section; the answer is a snapshot of its slot, which the panel polls until it is no longer pending. Loads run on
worker threads, so Fusion's UI thread is never blocked. Loaded sections are kept for the open design, so asking again does not query
again unless it is forced.

The panel's "structure" is the whole Bill of Materials of the design, every level read once, with the lines that cannot be published marked (Fusion Manage's own
Bill of Materials is not read for it). "mbom" is the manufacturing bills of materials of the design that Fusion Manage already holds, found by the design's lineage id and the asset id of its Components record,
and "mbom_number" whether an item number is taken by an item already (for a new one). "mbom_tree" is the whole Bill of Materials of the target
item as one tree (down to ``MBOM_DEPTH`` levels, each line with its item id and line id), for the structure viewer; it needs the target's id. It is the one
read of Fusion Manage's Bill of Materials.

"item_tabs:<id>" is about one Fusion Manage item (its id is what the panel sends as ``id``): which tabs it has, with counts and the user's permission, and
its urn, for the Details Panel's tabs. "item_view:<id>" is the same item laid out as the Item panel shows it (``ItemViewService.layout``: its sections of fields and
matrices, with the link of each picture, and no tabs or permissions: ``item_tabs`` reads those once), for the Details Panel's Item details tab; it is read when that tab is first opened. "item_picture:<link>" is one picture of such an item (its ``id`` is the link an image field gave), asked for by
the tab after it drew, so each picture shows a skeleton until it arrives.

The panel may name one of those items as the ``target`` of the sections that compare the design with Fusion Manage (its own properties and
its Bill of Materials): they then use the item number of the target, not the design's own. ``mbom_number`` is asked about the item number
it is given as its target. The target carries the item's id too (``target_id``) when Fusion Manage holds the item: that item is read, not
searched for by its number, which may have been changed. A target is part of what a slot was read for, so another target is read afresh and
a design's other slots are left alone.

The read of the whole structure from the Data Model is the long one, and it does not depend on the target: it is kept for the design (and the hub and
settings it was read under), so choosing another MBOM asks only what depends on the target. It is read again for a forced request (the panel's refresh)
and for another design.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID, WorkspaceConfig, kind_texts
from ..core.cancel import ADDIN, Cancelled, CancelToken
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch
from ..fm.bom import BomService
from ..fm.client import FmClient
from ..fm.components import manage_link
from ..fm.mbom import MbomService
from ..fm.item_view import ItemViewService
from ..fm.items import ItemService
from ..fm.permissions import denial, granted
from ..fm.tableaus import TableauService
from ..fm.tabs import TabService
from ..fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ..fusion_mfg.model_service import SECTION_NAMES, read_manage_item, read_section
from ..sync.bom_levels import mark_design_bom, search_design
from ..sync.item_compare import read_and_compare
from ..sync.item_number import item_number_of
from ..config.hub_context import HubContext, HubContexts

log = get_logger("panel_sections")

SUMMARY, PROPERTIES, COMPONENT, STRUCTURE, MBOM = "summary", "properties", "component", "structure", "mbom"
MBOM_NUMBER, MBOM_TREE = "mbom_number", "mbom_tree"
MBOM_DEPTH = 50   # levels of the target's Bill of Materials read, in the one read, for the structure viewer: a line at the last level whose own lines exist is marked ``cut``
ITEM_TABS, ITEM_VIEW, ITEM_PICTURE = "item_tabs", "item_view", "item_picture"
PANEL_SECTIONS = (*SECTION_NAMES, MBOM, MBOM_NUMBER, MBOM_TREE, ITEM_TABS, ITEM_VIEW, ITEM_PICTURE)
TARGETED = (PROPERTIES, STRUCTURE, MBOM_NUMBER, MBOM_TREE)   # sections about one item of Fusion Manage: they read the target's
# Sections with a slot for each ``id`` the panel sends: a component's (component, thumbnail), a Fusion Manage item's (item_tabs, item_view) or a picture's link (item_picture).
PER_COMPONENT = (COMPONENT, "thumbnail", ITEM_TABS, ITEM_VIEW, ITEM_PICTURE)
COMPONENT_KEYS = ("id", "item_number", "part_number", "description")


class PublishDenied(Exception):
    """The user's permissions in the Items workspace do not allow publishing."""


def publish_denial(fm: FmClient, cfg: WorkspaceConfig) -> str:
    """Why the user may not publish to the Items workspace ("" when they may, or when none is set up yet)."""
    if not cfg or not cfg.workspace_id:
        return ""
    kind = KINDS_BY_ID[ITEMS_KIND]
    return denial(fm, cfg.workspace_id, kind.required_permissions, kind_texts(kind)[0])


def entry(section: str = "", **changes: Any) -> Dict[str, Any]:
    """A section's state: loading (``pending``), done (``ok`` with ``data``) or failed (``message``)."""
    state: Dict[str, Any] = {"section": section, "pending": False, "ok": False, "data": None, "message": "", "denied": "", "key": "",
                             "progress": 0,   # while pending: how many relations of the structure are read so far (of a structure of several pages)
                             "stamp": "",     # what it was read under (``HubContext.stamp``): a publish made from it, or a reuse of it, needs it unchanged
                             "target": "",    # and the target it was read for (its item number, and its item id when Fusion Manage holds it)
                             "target_id": ""}
    state.update(changes)
    return state


class _Basis(NamedTuple):
    """What a slot was read for: the design (``key``), the hub, connection and workspace settings (``stamp``) and the target."""
    key: str
    stamp: str
    target: str = ""
    target_id: str = ""


class _Unavailable(Exception):
    """A section cannot be started (no design, no hub, or the design could not be named): the message is the slot's."""


class _Ask(NamedTuple):
    """A request for a section, resolved on Fusion's thread: the slot, the design it is for and the ``basis`` the slot is read for."""
    slot: str
    name: str
    model_id: str
    timestamp: str
    basis: _Basis
    context: HubContext


@dataclass
class _Load:
    """One load of one slot: what it reads, for which design, under which token, and under which hub, connection and workspace (``context``,
    taken when it was asked for). ``client`` and ``fm`` are made by the worker thread (see ``_prepare``)."""
    slot: str
    name: str
    key: str
    token: CancelToken
    model_id: str
    timestamp: str
    component: Dict[str, str]
    context: HubContext
    target: str = ""   # the item number of the item to compare the design with ("" is the design's own)
    target_id: str = ""   # the id of that item, when Fusion Manage holds it (found by lineage and asset): it is used, not a search by the number
    client: Optional[FusionGraphQlClient] = None
    fm: Optional[FmClient] = None

    @property
    def stamp(self) -> str:
        return self.context.stamp

    @property
    def basis(self) -> _Basis:
        return _Basis(self.key, self.stamp, self.target, self.target_id)

    @property
    def cfg(self) -> WorkspaceConfig:
        return self.context.cfg


class PublishSections:
    """The slots of the sections loaded for the open design. ``model_ref`` gives ``(model id, timestamp)`` of the open design."""

    def __init__(self, config: ConfigService, auth: AuthService, model_ref: Callable[[], Tuple[str, str]]) -> None:
        self._contexts, self._auth, self._model_ref = HubContexts(config, auth.session), auth, model_ref
        self._slots: Dict[str, Dict[str, Any]] = {name: entry(name) for name in SECTION_NAMES}   # a component's sections get a slot each ("component:<id>"), for the open design
        self._lock = threading.Lock()
        self._tokens: Dict[str, CancelToken] = {}   # slot -> the token of the load that fills it, ended when a newer load replaces it
        self._rows: Optional[Tuple[Tuple[str, str], List[Dict[str, Any]]]] = None   # ((design key, stamp), the rows of its whole structure), once one read has finished

    # ---- Asked by the panel -------------------------------------------------------

    def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start loading a section (unless it is loading or loaded for this design, and not ``force``d); the snapshot of its slot."""
        name = str(payload.get("section", ""))
        if name not in PANEL_SECTIONS:
            return entry(name, message=t("run.section_unknown", name=name))
        component = {k: str(payload.get(k) or "") for k in COMPONENT_KEYS}
        slot = f"{name}:{component['id']}" if name in PER_COMPONENT and component["id"] else name
        try:
            ask = self._ask_of(slot, name, payload)
        except _Unavailable as exc:
            return entry(slot, message=str(exc))
        with self._lock:
            snapshot, token = self._claim(ask, bool(payload.get("force")))
        if token is None:
            return snapshot
        basis = ask.basis
        load = _Load(slot, name, basis.key, token, ask.model_id, ask.timestamp, component, ask.context, basis.target, basis.target_id)
        threading.Thread(target=self._run, args=(load,), daemon=True).start()
        return snapshot

    def _ask_of(self, slot: str, name: str, payload: Dict[str, Any]) -> _Ask:
        """Resolve a request on Fusion's thread: the open design, the hub context and the target. Raises ``_Unavailable`` with the reason there is none."""
        try:
            model_id, timestamp = self._model_ref()
        except Exception as exc:
            log.exception("Could not start loading %s", slot)
            raise _Unavailable(str(exc)) from exc
        if not model_id:
            raise _Unavailable(t("run.section_no_model"))
        target = str(payload.get("target") or "") if name in TARGETED else ""
        target_id = str(payload.get("target_id") or "") if target else ""
        context, reason = self._contexts.attempt()   # taken now, on Fusion's thread: a hub opened or a user signed in meanwhile is not mixed in
        if context is None:
            raise _Unavailable(reason)
        return _Ask(slot, name, model_id, timestamp, _Basis(f"{model_id}|{timestamp}", context.stamp, target, target_id), context)

    def _claim(self, ask: _Ask, force: bool) -> Tuple[Dict[str, Any], Optional[CancelToken]]:
        """``(snapshot, token)``: the slot as it stands when it is loading or loaded for this basis (token None, nothing to start), else the slot
        made pending, with the token of the load that is to fill it. Called with the lock held."""
        slot, basis = ask.slot, ask.basis
        self._forget_other_designs(basis.key)
        if ask.name == STRUCTURE and force:
            self._rows = None   # a forced read is a fresh one: the kept rows are not served to it
        current = self._slots.get(slot) or entry(slot)
        if self._serves(current, ask, force):
            log.debug("%s requested: already %s, nothing started", slot, "loading" if current["pending"] else "loaded")
            return dict(current), None
        log.debug("%s requested: starting", slot)
        if slot in self._tokens:
            self._tokens[slot].cancel()   # what the slot was still reading for an earlier design (or the last try) is not wanted
        token = self._tokens[slot] = ADDIN.child(f"loading {slot} for the Publish panel")
        self._slots[slot] = entry(slot, pending=True, key=basis.key, stamp=basis.stamp, target=basis.target, target_id=basis.target_id)
        return dict(self._slots[slot]), token

    def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The snapshot of a slot, which the panel polls until it is no longer pending."""
        slot = str(payload.get("section", ""))
        with self._lock:
            return dict(self._slots.get(slot) or entry(slot, message=t("run.section_unknown", name=slot)))

    @staticmethod
    def _holds(state: Dict[str, Any], basis: _Basis) -> bool:
        """Whether a slot was filled, or is being filled, for this design and target under these settings (a changed hub, tenant or workspace
        setting makes what was read, and compared with Fusion Manage, no longer right)."""
        return (state["key"], state["stamp"], state["target"], state["target_id"]) == basis

    def _serves(self, current: Dict[str, Any], ask: _Ask, force: bool) -> bool:
        """Whether the slot is answered as it is: it is loading or loaded for this basis, and the request is not forced. The MBOM tree is never
        served from a copy kept here: its line ids are what a publish changes, and Fusion Manage changes under the panel."""
        if force or ask.name == MBOM_TREE:
            return False
        return self._holds(current, ask.basis) and (current["pending"] or current["ok"])

    def _forget_other_designs(self, key: str) -> None:
        """Drop the slots of components made for another design, and end what they were still reading (called with the lock held): they are
        never asked for again, and would pile up as designs are opened. The kept rows of another design go too."""
        for slot in [s for s, state in self._slots.items() if s not in SECTION_NAMES and state["key"] != key]:
            del self._slots[slot]
            token = self._tokens.pop(slot, None)
            if token:
                token.cancel()
        if self._rows and self._rows[0][0] != key:
            self._rows = None

    # ---- Worker thread ------------------------------------------------------------

    def _prepare(self, load: _Load) -> None:
        """Make the clients of a load: they share its token, so replacing the load ends what they are reading."""
        load.client = FusionGraphQlClient(load.token)
        load.fm = FmClient(load.context.settings, self._auth, load.token)

    def _run(self, load: _Load) -> None:
        try:
            self._prepare(load)
            overall = Stopwatch()
            if load.name == SUMMARY:   # the first section: when it is denied nothing else is asked for
                asked = Stopwatch()
                message = publish_denial(load.fm, load.cfg)
                log.debug("Checked the permissions in %.2fs", asked.lap())
                if message:
                    raise PublishDenied(message)
            data = self._load(load)
            log.info("Loaded %s of %s", load.slot, load.model_id)
            log.debug("TIMING %s: %.2fs in all", load.slot, overall.lap())
            outcome = entry(load.slot, ok=True, data=data, key=load.key, stamp=load.stamp, target=load.target, target_id=load.target_id)
        except Cancelled:   # a newer load replaced this one (another design, or a reload): the slot is left for that to fill
            log.info("Loading %s was cancelled", load.slot)
            return
        except PublishDenied as exc:   # not an error: the panel says so, in place of the item
            log.info("No permission to publish: %s", exc)
            outcome = entry(load.slot, message=str(exc), denied=str(exc), key=load.key, target=load.target, target_id=load.target_id)
        except Exception as exc:  # never leave the panel waiting
            log.exception("Loading %s failed", load.slot)
            outcome = entry(load.slot, message=str(exc) or type(exc).__name__, key=load.key, target=load.target, target_id=load.target_id)
        with self._lock:
            if self._waits_for(load):   # ignore a result for a design that is no longer open
                self._slots[load.slot] = outcome

    def _waits_for(self, load: _Load) -> bool:
        """Whether the slot of ``load`` is still waiting for it, not for a newer load or another design (called with the lock held)."""
        slot = self._slots.get(load.slot)
        return slot is not None and self._holds(slot, load.basis) and slot["pending"]

    def _note(self, load: _Load, **changes: Any) -> None:
        """Say how far a load is (while it is still the one the slot waits for)."""
        with self._lock:
            if self._waits_for(load):
                self._slots[load.slot].update(changes)

    def _summary_of(self, load: _Load) -> Dict[str, Any]:
        """The summary read for this design: the sections after it need the design's component id, composition and item number (the target's,
        when the load is for one)."""
        with self._lock:
            summary = self._slots[SUMMARY]
            data = dict(summary["data"] or {}) if self._holds(summary, _Basis(load.key, load.stamp)) else {}
        return {**data, "item_number": load.target} if load.target else data

    @staticmethod
    def _mbom(load: _Load, summary: Dict[str, Any]) -> Any:
        """``mbom``: the MBOM items Fusion Manage holds for the design. ``mbom_number``: whether the target's item number is taken already."""
        if not load.cfg.workspace_id:
            raise ValueError(t("run.compare_no_workspace"))
        if load.name == MBOM_NUMBER:
            return {"taken": MbomService(load.fm).number_taken(load.cfg.workspace_id, load.target)}
        record = read_manage_item(load.client, summary, summary.get("component_id", ""), load.timestamp)   # the design's record in the Components workspace
        link = manage_link(record["urn"], record["url"])
        if not link:
            raise ValueError(t("data.fm_mbom_not_linked"))
        return MbomService(load.fm).find(load.cfg.workspace_id, summary.get("lineage", ""), link, load.cfg.item_number_field())

    @staticmethod
    def _workspace_of(load: _Load) -> str:
        """The Items workspace's id; raises when Settings name none."""
        if not load.cfg.workspace_id:
            raise ValueError(t("run.compare_no_workspace"))
        return str(load.cfg.workspace_id)

    @classmethod
    def _item_of(cls, load: _Load) -> Tuple[str, str]:
        """``(workspace id, item id)`` of a section about one Fusion Manage item (the panel sends the item's id as ``id``); raises when either is missing."""
        workspace_id = cls._workspace_of(load)
        if not load.component["id"]:
            raise ValueError(t("app.lookup_no_item"))
        return workspace_id, load.component["id"]

    @classmethod
    def _item_tabs(cls, load: _Load) -> Dict[str, Any]:
        """``item_tabs``: which tabs the item has (with counts and whether the user may open them), and its urn, which the Files tab needs for its links."""
        workspace_id, item_id = cls._item_of(load)
        held = granted(load.fm, workspace_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            tabs = pool.submit(TabService(load.fm).read, workspace_id, item_id, held)
            urn = pool.submit(ItemService(load.fm).urn, workspace_id, item_id)
            return {"workspace_id": workspace_id, "item_id": item_id, "item_urn": urn.result(), "tabs": tabs.result()}

    @classmethod
    def _item_view(cls, load: _Load) -> Dict[str, Any]:
        """``item_view``: the item as the Item panel shows it, as ``ItemViewService.layout`` answers (title, header, state, url, ``sections`` of fields and matrices,
        ``item_id``, ``workspace_id``, ``item_urn``). No tabs or permissions (``item_tabs`` has them) and no pictures (an image field comes with its ``link`` and no value;
        the page asks for each with ``item_picture``)."""
        workspace_id, item_id = cls._item_of(load)
        return ItemViewService(load.fm).layout(workspace_id, item_id, pictures=False)

    @classmethod
    def _item_picture(cls, load: _Load) -> Dict[str, Any]:
        """``item_picture``: ``{"image": data uri}`` of the picture at the link the page sends as ``id``, which an image field of the item gave
        (``TableauService.picture`` refuses a link that is not a picture of this workspace)."""
        return TableauService(load.fm).picture(cls._workspace_of(load), load.component["id"])

    def _structure_rows(self, load: _Load, read: Callable[[], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """The rows of the whole structure of the design: those kept by an earlier read under the same hub and settings, else ``read()``, which is kept once it
        has finished (a load that was replaced meanwhile keeps nothing, so a forced read is never given what it replaced)."""
        wanted = (load.key, load.stamp)
        with self._lock:
            if self._rows and self._rows[0] == wanted:
                log.debug("%s: the structure was read already, not read again", load.slot)
                return self._rows[1]
        rows = read()
        with self._lock:
            if not load.token.cancelled:
                self._rows = (wanted, rows)
        return rows

    def _load(self, load: _Load) -> Any:
        """What the section holds: read from the Data Model, and compared with Fusion Manage for the properties, which the Details Panel shows."""
        if load.name == ITEM_TABS:   # about a Fusion Manage item (or one of its pictures), not the design: nothing here is read from the Data Model
            return self._item_tabs(load)
        if load.name == ITEM_VIEW:
            return self._item_view(load)
        if load.name == ITEM_PICTURE:
            return self._item_picture(load)
        summary = self._summary_of(load)
        read = self._reader(load, summary)
        if load.name in (PROPERTIES, COMPONENT):
            return self._compared(load, summary, read)
        if load.name in (MBOM, MBOM_NUMBER):
            return self._mbom(load, summary)
        if load.name == MBOM_TREE:
            return self._mbom_tree(load)
        if load.name == STRUCTURE:
            return self._structure(load, summary, read)
        return self._summary_data(load, read())

    def _reader(self, load: _Load, summary: Dict[str, Any]) -> Callable[[], Any]:
        """The read of the section from the Data Model, which reports its progress to the slot."""
        physical = load.cfg.maps_physical()
        watch = Stopwatch()

        def read() -> Any:
            result = read_section(load.client, load.name, load.model_id, load.timestamp, summary,
                                  load.component.get("id", ""), physical, lambda count: self._note(load, progress=count))
            log.debug("TIMING %s: %.2fs of it reading the Data Model (physical=%s)", load.slot, watch.lap(), physical)
            return result["properties"] if load.name == COMPONENT else result

        return read

    @staticmethod
    def _compared(load: _Load, summary: Dict[str, Any], read: Callable[[], Any]) -> Dict[str, Any]:
        """``properties`` and ``component``: what ``read`` gives, compared with the item in Fusion Manage."""
        properties, compared = read_and_compare(read, load.component if load.name == COMPONENT else summary, load.cfg, load.fm,
                                                load.target_id if load.name == PROPERTIES else "")
        return {"compare": compared, **({"count": len(properties)} if load.name == PROPERTIES else {})}

    @staticmethod
    def _mbom_tree(load: _Load) -> Any:
        """``mbom_tree``: the item is read by its id: a design with no MBOM item has no tree, and the viewer starts from the EBOM."""
        if not load.cfg.workspace_id:
            raise ValueError(t("run.compare_no_workspace"))
        if not load.target_id:
            raise ValueError(t("run.section_no_mbom_item"))
        return BomService(load.fm).tree(load.cfg.workspace_id, load.target_id, MBOM_DEPTH)

    def _structure(self, load: _Load, summary: Dict[str, Any], read: Callable[[], Any]) -> Any:
        """``structure``: the design's whole Bill of Materials with the lines that cannot be published marked."""
        known = [{"id": load.target_id}] if load.target_id else None   # found by lineage and asset: the number may have been changed since
        with ThreadPoolExecutor(max_workers=1) as pool:
            searching = None if known else pool.submit(search_design, load.fm, load.cfg, summary)   # else the number is searched while it is read
            rows = self._structure_rows(load, read)
            hits = known or searching.result()
        return mark_design_bom(rows, summary, hits)

    @staticmethod
    def _summary_data(load: _Load, data: Any) -> Any:
        """A section read as it is, except the summary: it needs an item number, and carries what the viewer needs to know of the settings."""
        if load.name != SUMMARY:
            return data
        if not item_number_of(data):   # no item number: never published, so nothing here applies
            raise PublishDenied(t("run.section_no_number"))
        make_buy = load.cfg.make_buy   # whether a bought version can be made
        return {**data, "make_buy": make_buy.is_set(), "bought_suffix": make_buy.suffix if make_buy.is_set() else ""}

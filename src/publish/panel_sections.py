"""The sections of the open design that the Publish Item panel asks for, and how each is loaded.

The panel asks for a section; the answer is a snapshot of its slot, which the panel polls until it is no longer pending. Loads run on
worker threads, so Fusion's UI thread is never blocked. Loaded sections are kept for the open design, so asking again does not query
again unless it is forced.

The panel's "structure" is the first level of the Bill of Materials only. "children" is the level under one assembly (a slot of its own
for each), and "tree" is the whole tree (Expand all, and publishing, which needs every line).
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID, WorkspaceConfig
from ..core.cancel import ADDIN, Cancelled, CancelToken
from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch
from ..fm.client import FmClient
from ..fm.permissions import denial
from ..fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ..fusion_mfg.model_service import LEVEL, SECTION_NAMES, STRUCTURE, read_section
from ..sync.bom_levels import compare_design_bom, compare_level, search_design
from ..sync.item_compare import read_and_compare
from ..sync.item_number import item_number_of
from .context import PublishContext, capture_context

log = get_logger("panel_sections")

SUMMARY, PROPERTIES, COMPONENT, STRUCTURE_VIEW, TREE, CHILDREN = "summary", "properties", "component", "structure", "tree", "children"
PANEL_SECTIONS = (*SECTION_NAMES, TREE, CHILDREN)
PER_COMPONENT = (COMPONENT, "thumbnail", CHILDREN)   # sections with a slot for each component
READS = {STRUCTURE_VIEW: LEVEL, TREE: STRUCTURE, CHILDREN: LEVEL}   # what the Data Model is asked for, where it is not the section's own name
COMPONENT_KEYS = ("id", "item_number", "part_number", "description",
                  "skip", "compared")   # ``skip`` and ``compared`` ("1" or ""): only a ``children`` read uses them, to compare the level with Fusion Manage


class PublishDenied(Exception):
    """The user's permissions in the Items workspace do not allow publishing."""


def publish_denial(fm: FmClient, cfg: WorkspaceConfig) -> str:
    """Why the user may not publish to the Items workspace ("" when they may, or when none is set up yet)."""
    if not cfg or not cfg.workspace_id:
        return ""
    kind = KINDS_BY_ID[ITEMS_KIND]
    return denial(fm, cfg.workspace_id, kind.required_permissions, kind.title)


def entry(section: str = "", **changes: Any) -> Dict[str, Any]:
    """A section's state: loading (``pending``), done (``ok`` with ``data``) or failed (``message``)."""
    state: Dict[str, Any] = {"section": section, "pending": False, "ok": False, "data": None, "message": "", "denied": "", "key": "",
                             "progress": 0,   # while pending: how many relations of the structure are read so far (of a structure of several pages)
                             "stage": "",     # while pending: "comparing" once the structure is read and Fusion Manage is being asked
                             "hub": ""}       # the Fusion hub it was read under: a publish made from it must find that hub still active
    state.update(changes)
    return state


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
    context: Optional[PublishContext] = None
    client: Optional[FusionGraphQlClient] = None
    fm: Optional[FmClient] = None

    @property
    def hub(self) -> str:
        return self.context.hub_id if self.context else ""

    @property
    def cfg(self) -> Optional[WorkspaceConfig]:
        return self.context.cfg if self.context else None


class PublishSections:
    """The slots of the sections loaded for the open design. ``model_ref`` gives ``(model id, timestamp)`` of the open design."""

    def __init__(self, config: ConfigService, auth: AuthService, model_ref: Callable[[], Tuple[str, str]]) -> None:
        self._config, self._auth, self._model_ref = config, auth, model_ref
        self._slots: Dict[str, Dict[str, Any]] = {name: entry(name) for name in SECTION_NAMES}   # a component's sections get a slot each ("component:<id>"), for the open design
        self._lock = threading.Lock()
        self._tokens: Dict[str, CancelToken] = {}   # slot -> the token of the load that fills it, ended when a newer load replaces it

    # ---- Asked by the panel -------------------------------------------------------

    def request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start loading a section (unless it is loading or loaded for this design, and not ``force``d); the snapshot of its slot."""
        name = str(payload.get("section", ""))
        if name not in PANEL_SECTIONS:
            return entry(name, message=f"Unknown section: {name}")
        component = {k: str(payload.get(k) or "") for k in COMPONENT_KEYS}
        slot = f"{name}:{component['id']}" if name in PER_COMPONENT and component["id"] else name
        try:
            model_id, timestamp = self._model_ref()
        except Exception as exc:
            log.exception("Could not start loading %s", slot)
            return entry(slot, message=str(exc))
        if not model_id:
            return entry(slot, message="Could not find the Data Model id of the open design.")
        key = f"{model_id}|{timestamp}"
        try:   # the hub, connection and workspace this load reads under are taken now, on Fusion's thread: a hub opened meanwhile is not mixed in
            context = capture_context(self._config)
        except Exception as exc:
            log.exception("Could not read the settings for %s", slot)
            return entry(slot, message=str(exc) or type(exc).__name__)
        with self._lock:
            self._forget_other_designs(key)
            current = self._slots.get(slot) or entry(slot)
            if not payload.get("force") and current["key"] == key and (current["pending"] or current["ok"]):
                log.debug("%s requested: already %s, nothing started", slot, "loading" if current["pending"] else "loaded")
                return dict(current)
            log.debug("%s requested: starting", slot)
            if slot in self._tokens:
                self._tokens[slot].cancel()   # what the slot was still reading for an earlier design (or the last try) is not wanted
            token = self._tokens[slot] = ADDIN.child(f"loading {slot} for the Publish panel")
            self._slots[slot] = entry(slot, pending=True, key=key, hub=context.hub_id)
            snapshot = dict(self._slots[slot])
        threading.Thread(target=self._run, args=(_Load(slot, name, key, token, model_id, timestamp, component, context),), daemon=True).start()
        return snapshot

    def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The snapshot of a slot, which the panel polls until it is no longer pending."""
        slot = str(payload.get("section", ""))
        with self._lock:
            return dict(self._slots.get(slot) or entry(slot, message=f"Unknown section: {slot}"))

    def _forget_other_designs(self, key: str) -> None:
        """Drop the slots of components made for another design, and end what they were still reading (called with the lock held): they are
        never asked for again, and would pile up as designs are opened."""
        for slot in [s for s, state in self._slots.items() if s not in SECTION_NAMES and state["key"] != key]:
            del self._slots[slot]
            token = self._tokens.pop(slot, None)
            if token:
                token.cancel()

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
            outcome = entry(load.slot, ok=True, data=data, key=load.key, hub=load.hub)
        except Cancelled:   # a newer load replaced this one (another design, or a reload): the slot is left for that to fill
            log.info("Loading %s was cancelled", load.slot)
            return
        except PublishDenied as exc:   # not an error: the panel says so, in place of the item
            log.info("No permission to publish: %s", exc)
            outcome = entry(load.slot, message=str(exc), denied=str(exc), key=load.key)
        except Exception as exc:  # never leave the panel waiting
            log.exception("Loading %s failed", load.slot)
            outcome = entry(load.slot, message=str(exc) or type(exc).__name__, key=load.key)
        with self._lock:
            if self._waits_for(load):   # ignore a result for a design that is no longer open
                self._slots[load.slot] = outcome

    def _waits_for(self, load: _Load) -> bool:
        """Whether the slot of ``load`` is still waiting for it, not for a newer load or another design (called with the lock held)."""
        slot = self._slots.get(load.slot)
        return slot is not None and slot["key"] == load.key and slot["pending"]

    def _note(self, load: _Load, **changes: Any) -> None:
        """Say how far a load is (while it is still the one the slot waits for)."""
        with self._lock:
            if self._waits_for(load):
                self._slots[load.slot].update(changes)

    def _summary_of(self, load: _Load) -> Dict[str, Any]:
        """The summary read for this design: the sections after it need the design's component id, composition and item number."""
        with self._lock:
            summary = self._slots[SUMMARY]
            return dict(summary["data"] or {}) if summary["key"] == load.key else {}

    def _load(self, load: _Load) -> Any:
        """What the section holds: read from the Data Model, and compared with Fusion Manage where the panel shows the comparison."""
        summary = self._summary_of(load)
        physical = load.cfg.maps_physical() if load.cfg else False
        watch = Stopwatch()

        def read() -> Any:
            result = read_section(load.client, READS.get(load.name, load.name), load.model_id, load.timestamp, summary,
                                  load.component.get("id", ""), physical, lambda count: self._note(load, progress=count))
            log.debug("TIMING %s: %.2fs of it reading the Data Model (physical=%s)", load.slot, watch.lap(), physical)
            return result["properties"] if load.name == COMPONENT else result

        if load.name in (PROPERTIES, COMPONENT):
            properties, compared = read_and_compare(read, load.component if load.name == COMPONENT else summary, load.cfg, load.fm)
            return {"compare": compared, **({"count": len(properties)} if load.name == PROPERTIES else {})}
        if load.name == CHILDREN:
            c = load.component
            return compare_level(read(), c["item_number"], bool(c["skip"]), bool(c["compared"]), load.cfg, load.fm)
        if load.name in (STRUCTURE_VIEW, TREE):
            with ThreadPoolExecutor(max_workers=1) as pool:
                searching = pool.submit(search_design, load.fm, load.cfg, summary)   # the design's number is searched while its structure is read
                rows = read()
                self._note(load, stage="comparing")
                hits = searching.result()
            return compare_design_bom(rows, summary, load.cfg, load.fm, hits)
        data = read()
        if load.name == SUMMARY and not item_number_of(data):   # no item number: never published, so nothing here applies
            raise PublishDenied("This design has no item number, so it has not been published to Fusion Manage.")
        return data

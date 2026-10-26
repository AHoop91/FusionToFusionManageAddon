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
from typing import Any, Callable, Dict, Tuple

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
from ..config.workspace_models import ITEMS_KIND, KINDS_BY_ID, WorkspaceConfig
from ..core.cancel import ADDIN, Cancelled, CancelToken
from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch
from ..fm.client import FmClient
from ..fm.permissions import denial
from ..fusion_mfg.graphql_client import MfgGraphQlClient
from ..fusion_mfg.model_service import LEVEL, SECTION_NAMES, STRUCTURE, read_section
from ..sync.bom_levels import compare_design_bom, compare_level, search_design
from ..sync.item_compare import item_number_of, read_and_compare

log = get_logger("panel_sections")

TREE, CHILDREN = "tree", "children"
PANEL_SECTIONS = (*SECTION_NAMES, TREE, CHILDREN)
PER_COMPONENT = ("component", "thumbnail", CHILDREN)   # sections with a slot for each component
READS = {"structure": LEVEL, TREE: STRUCTURE, CHILDREN: LEVEL}   # what the Data Model is asked for, where it is not the section's own name
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
                             "stage": ""}     # while pending: "comparing" once the structure is read and Fusion Manage is being asked
    state.update(changes)
    return state


@dataclass
class _Load:
    """One load of one slot: what it reads, for which design, and with which clients."""
    slot: str
    name: str
    key: str
    client: MfgGraphQlClient
    fm: FmClient
    cfg: WorkspaceConfig
    model_id: str
    time: str
    component: Dict[str, str]


class PublishSections:
    """The slots of the sections loaded for the open design. ``model_ref`` gives ``(model id, timestamp)`` of the open design."""

    def __init__(self, config: ConfigService, auth: AuthService, model_ref: Callable[[], Tuple[str, str]]) -> None:
        self._config, self._auth, self._model_ref = config, auth, model_ref
        self._slots: Dict[str, Dict[str, Any]] = {name: entry(name) for name in SECTION_NAMES}   # a component's sections get a slot each ("component:<id>")
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
            model_id, time = self._model_ref()
            settings = self._config.effective_settings()
            token = ADDIN.child(f"loading {slot} for the Publish panel")
            client, fm = MfgGraphQlClient(settings, self._auth, token), FmClient(settings, self._auth, token)
            cfg = self._config.config.workspaces.get(ITEMS_KIND)
        except Exception as exc:
            log.exception("Could not start loading %s", slot)
            return entry(slot, message=str(exc))
        if not model_id:
            return entry(slot, message="Could not find the Data Model id of the open design.")
        key = f"{model_id}|{time}"
        with self._lock:
            current = self._slots.get(slot) or entry(slot)
            if not payload.get("force") and current["key"] == key and (current["pending"] or current["ok"]):
                log.debug("%s requested: already %s, nothing started", slot, "loading" if current["pending"] else "loaded")
                return dict(current)
            log.debug("%s requested: starting", slot)
            if slot in self._tokens:
                self._tokens[slot].cancel()   # what the slot was still reading for an earlier design (or the last try) is not wanted
            self._tokens[slot] = token
            self._slots[slot] = entry(slot, pending=True, key=key)
            snapshot = dict(self._slots[slot])
        load = _Load(slot, name, key, client, fm, cfg, model_id, time, component)
        threading.Thread(target=self._run, args=(load,), daemon=True).start()
        return snapshot

    def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The snapshot of a slot, which the panel polls until it is no longer pending."""
        slot = str(payload.get("section", ""))
        with self._lock:
            return dict(self._slots.get(slot) or entry(slot, message=f"Unknown section: {slot}"))

    # ---- Worker thread ------------------------------------------------------------

    def _run(self, load: _Load) -> None:
        try:
            whole = Stopwatch()
            if load.name == "summary":   # the first section: when it is denied nothing else is asked for
                asked = Stopwatch()
                message = publish_denial(load.fm, load.cfg)
                log.debug("Checked the permissions in %.2fs", asked.lap())
                if message:
                    raise PublishDenied(message)
            data = self._load(load)
            log.info("Loaded %s of %s", load.slot, load.model_id)
            log.debug("TIMING %s: %.2fs in all", load.slot, whole.lap())
            outcome = entry(load.slot, ok=True, data=data, key=load.key)
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
            if self._slots[load.slot]["key"] == load.key:   # ignore a result for a design that is no longer open
                self._slots[load.slot] = outcome

    def _note(self, load: _Load, **changes: Any) -> None:
        """Say how far a load is (while it is still the one the slot waits for)."""
        with self._lock:
            slot = self._slots[load.slot]
            if slot["key"] == load.key and slot["pending"]:
                slot.update(changes)

    def _summary_of(self, load: _Load) -> Dict[str, Any]:
        """The summary read for this design: the sections after it need the design's component id, composition and item number."""
        with self._lock:
            summary = self._slots["summary"]
            return dict(summary["data"] or {}) if summary["key"] == load.key else {}

    def _load(self, load: _Load) -> Any:
        """What the section holds: read from the Data Model, and compared with Fusion Manage where the panel shows the comparison."""
        summary = self._summary_of(load)
        physical = load.cfg.maps_physical() if load.cfg else False
        watch = Stopwatch()

        def read() -> Any:
            result = read_section(load.client, READS.get(load.name, load.name), load.model_id, load.time, summary,
                                  load.component.get("id", ""), physical, lambda count: self._note(load, progress=count))
            log.debug("TIMING %s: %.2fs of it reading the Data Model (physical=%s)", load.slot, watch.lap(), physical)
            return result["properties"] if load.name == "component" else result

        if load.name in ("properties", "component"):
            properties, compared = read_and_compare(read, load.component if load.name == "component" else summary, load.cfg, load.fm)
            return {"compare": compared, **({"count": len(properties)} if load.name == "properties" else {})}
        if load.name == CHILDREN:
            c = load.component
            return compare_level(read(), c["item_number"], bool(c["skip"]), bool(c["compared"]), load.cfg, load.fm)
        if load.name in ("structure", TREE):
            with ThreadPoolExecutor(max_workers=1) as pool:
                searching = pool.submit(search_design, load.fm, load.cfg, summary)   # the design's number is searched while its structure is read
                rows = read()
                self._note(load, stage="comparing")
                hits = searching.result()
            return compare_design_bom(rows, summary, load.cfg, load.fm, hits)
        data = read()
        if load.name == "summary" and not item_number_of(data):   # no item number: never published, so nothing here applies
            raise PublishDenied("This design has no item number, so it has not been published to Fusion Manage.")
        return data

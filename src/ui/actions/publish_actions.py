"""Palette actions that load the open design's model for the Publish Item panel.

The summary loads first. The rest loads only when the panel asks for it (a tab
opening, a component being clicked), each on its own worker thread.
"""

import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.workspace_models import ITEMS_KIND, KINDS_BY_ID, PHYSICAL_PREFIX, WorkspaceConfig
from ...core.logging_setup import get_logger
from ...core.timing import Stopwatch
from ...fm.bom import BomService
from ...fm.client import FmClient
from ...fm.items import ItemService
from ...fm.permissions import denial
from ...fusion_mfg.graphql_client import MfgGraphQlClient
from ...fusion_mfg.model_service import SECTION_NAMES, read_section
from ...sync.bom_compare import compare_bom
from ...sync.item_compare import compare_with_item, item_number_of, lookup_item
from ..message_bridge import MessageBridge

log = get_logger("publish_actions")


class PublishDenied(Exception):
    """The user's permissions in the Items workspace do not allow publishing."""


def publish_denial(fm: FmClient, cfg: WorkspaceConfig) -> str:
    """Why the user may not publish to the Items workspace ("" when they may, or when none is set up yet)."""
    if not cfg or not cfg.workspace_id:
        return ""
    kind = KINDS_BY_ID[ITEMS_KIND]
    return denial(fm, cfg.workspace_id, kind.required_permissions, kind.title)


def _search_design(fm: FmClient, cfg: WorkspaceConfig, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The Fusion Manage items with the design's number (none when there is nothing to look for). It needs only the
    summary, so it runs while the structure is still being read."""
    number = item_number_of(summary)
    if not cfg or not cfg.workspace_id or not number:
        return []
    return ItemService(fm).search(cfg.workspace_id, number)


def _compare_bom(rows: List[Dict[str, Any]], summary: Dict[str, Any], cfg: WorkspaceConfig,
                 fm: FmClient, chosen: str, hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mark each BOM row against the Fusion Manage BOM of the open design. Runs on a worker thread.

    ``hits`` are the Fusion Manage items found for the design's number (``_search_design``).
    One BOM call, deep enough for the whole tree, covers every assembly. Rows stay
    unchecked (no status) when the design is not compared. When the design matches
    several items and none is chosen, ``pick`` is set and the panel waits for the choice.
    ``fm_item_id`` is the Fusion Manage item compared with, empty when there is none (the Add Items picker needs it).
    """
    number = item_number_of(summary)
    log.info("Design structure of %s: %s", number or "(no number)", "; ".join(
        f"{'  ' * int(r['level'])}{r['item_number'] or r['part_number']} x{r['quantity']}" for r in rows) or "no components")
    if not cfg or not cfg.workspace_id or not number:
        return {"rows": rows, "pick": False}
    if not hits:
        return {"rows": compare_bom(rows, number, {}), "pick": False}   # the design is new, so every line is
    picked = next((h for h in hits if h["id"] == chosen), None) or (hits[0] if len(hits) == 1 else None)
    if not picked:
        return {"rows": rows, "pick": True}
    depth = max([int(r["level"]) for r in rows] + [0]) + 1
    # A Fusion Manage or sign-in failure is not caught: the section fails and the panel offers Retry,
    # rather than caching a table that looks compared but is not.
    watch = Stopwatch()
    fm_bom = BomService(fm).read(cfg.workspace_id, picked["id"], depth)
    read_seconds = watch.lap()
    log.info("Fusion Manage BOM of %s: %d parent(s), %d line(s)", number, len(fm_bom), sum(len(v) for v in fm_bom.values()))
    compared = compare_bom(rows, number, fm_bom)
    log.debug("Compared the BOM of %s: Fusion Manage read %.2fs (depth %d), compare %.3fs, %d rows", number, read_seconds, depth,
              watch.lap(), len(rows))
    return {"rows": compared, "pick": False, "fm_item_id": picked["id"]}


def _model_ref() -> Tuple[str, str]:
    """``(model id, timestamp)`` of the open design, or ``("", "")``.

    Both come from the design's root data component. The timestamp pins the
    query to the version open in Fusion and may be empty. Runs on the UI thread.
    """
    import adsk.core
    import adsk.fusion
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if design is None:
        return "", ""
    data = design.rootDataComponent
    return str(data.mfgdmModelId or ""), str(data.timestamp or "")


def _entry(section: str = "", **changes: Any) -> Dict[str, Any]:
    """A section's state: loading (``pending``), done (``ok`` with ``data``) or failed (``message``)."""
    entry: Dict[str, Any] = {"section": section, "pending": False, "ok": False, "data": None, "message": "", "denied": "", "key": "",
                             "progress": 0,   # while pending: how many relations of the structure are read so far (of a structure of several pages)
                             "stage": ""}     # while pending: "comparing" once the structure is read and Fusion Manage is being asked
    entry.update(changes)
    return entry


def register_publish_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the section load handlers.

    Queries run on worker threads and the panel polls for the answer, so
    Fusion's UI thread is never blocked. Loaded sections are kept for the
    open design, so switching back to a tab does not query again.
    """

    # One slot per section; a component's properties get a slot each ("component:<id>").
    sections: Dict[str, Dict[str, Any]] = {name: _entry(name) for name in SECTION_NAMES}
    lock = threading.Lock()

    def run(slot: str, name: str, key: str, client: MfgGraphQlClient, fm: FmClient, cfg: WorkspaceConfig,
            model_id: str, time: str, component: Dict[str, str], chosen: str) -> None:
        try:
            whole = Stopwatch()
            if name == "summary":   # the first section: when it is denied nothing else is asked for
                asked = Stopwatch()
                message = publish_denial(fm, cfg)
                log.debug("Checked the permissions in %.2fs", asked.lap())
                if message:
                    raise PublishDenied(message)
            reading = Stopwatch()
            with lock:
                summary = dict(sections["summary"]["data"] or {}) if sections["summary"]["key"] == key else {}
            physical = any(m.source.startswith(PHYSICAL_PREFIX) and m.fm_field_id for m in cfg.mappings) if cfg else False
            read_seconds = 0.0

            def note(**changes: Any) -> None:
                with lock:
                    if sections[slot]["key"] == key and sections[slot]["pending"]:
                        sections[slot].update(changes)

            def note_progress(count: int) -> None:
                note(progress=count)

            def read() -> Any:
                nonlocal read_seconds
                result = read_section(client, name, model_id, time, summary, component.get("id", ""), physical, note_progress)
                read_seconds = reading.lap()
                return result["properties"] if name == "component" else result

            if name in ("properties", "component"):
                subject = component if name == "component" else summary
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(read)
                    lookup = lookup_item(subject, cfg, fm, chosen)   # Fusion Manage is asked while the Data Model is read
                properties = pending.result()
                data = {"compare": compare_with_item(properties, subject, cfg, lookup)}
                if name == "properties":
                    data["count"] = len(properties)
            elif name == "structure":
                with ThreadPoolExecutor(max_workers=1) as pool:
                    searching = pool.submit(_search_design, fm, cfg, summary)   # the design's number is searched while its structure is read
                    rows = read()
                    note(stage="comparing")
                    hits = searching.result()
                data = _compare_bom(rows, summary, cfg, fm, chosen, hits)
            else:
                data = read()
            log.info("Loaded %s of %s", slot, model_id)
            log.debug("TIMING %s: %.2fs in all, %.2fs of it reading the Data Model (physical=%s)", slot, whole.lap(), read_seconds, physical)
            outcome = _entry(slot, ok=True, data=data, key=key)
        except PublishDenied as exc:   # not an error: the panel says so, in place of the item
            log.info("No permission to publish: %s", exc)
            outcome = _entry(slot, message=str(exc), denied=str(exc), key=key)
        except Exception as exc:  # never leave the panel waiting
            log.exception("Loading %s failed", slot)
            outcome = _entry(slot, message=str(exc) or type(exc).__name__, key=key)
        with lock:
            if sections[slot]["key"] == key:   # ignore a result for a design that is no longer open
                sections[slot] = outcome

    def load_publish_section(payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("section", ""))
        if name not in SECTION_NAMES:
            return _entry(name, message=f"Unknown section: {name}")
        component = {k: str(payload.get(k) or "") for k in ("id", "item_number", "part_number", "description")}
        chosen = str(payload.get("fm_item") or "")
        slot = f"component:{component['id']}" if name == "component" else name
        try:
            model_id, time = _model_ref()
            settings = config.effective_settings()
            client, fm = MfgGraphQlClient(settings, auth), FmClient(settings, auth)
            cfg = config.config.workspaces.get(ITEMS_KIND)
        except Exception as exc:
            log.exception("Could not start loading %s", slot)
            return _entry(slot, message=str(exc))
        if not model_id:
            return _entry(slot, message="Could not find the Data Model id of the open design.")
        key = f"{model_id}|{time}"
        with lock:
            current = sections.get(slot) or _entry(slot)
            if not payload.get("force") and current["key"] == key and (current["pending"] or current["ok"]):
                log.debug("%s requested: already %s, nothing started", slot, "loading" if current["pending"] else "loaded")
                return dict(current)
            log.debug("%s requested: starting", slot)
            sections[slot] = _entry(slot, pending=True, key=key)
            snapshot = dict(sections[slot])
        threading.Thread(target=run, args=(slot, name, key, client, fm, cfg, model_id, time, component, chosen),
                         daemon=True).start()
        return snapshot

    def load_publish_section_status(payload: Dict[str, Any]) -> Dict[str, Any]:
        slot = str(payload.get("section", ""))
        with lock:
            return dict(sections.get(slot) or _entry(slot, message=f"Unknown section: {slot}"))

    def open_url(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open a link in the system browser (a palette cannot open one itself). https, or http to this computer (Vault)."""
        url = str(payload.get("url", ""))
        if not url.lower().startswith(("https://", "http://localhost/", "http://127.0.0.1/")):
            raise ValueError("Only https links can be opened.")
        webbrowser.open(url)
        return {}

    def get_publish_model_key(_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Cheap check of which design is open, so the panel reloads only on a change."""
        model_id, time = _model_ref()
        return {"key": f"{model_id}|{time}" if model_id else ""}

    bridge.register("load_publish_section", load_publish_section)
    bridge.register("load_publish_section_status", load_publish_section_status)
    bridge.register("get_publish_model_key", get_publish_model_key)
    bridge.register("open_url", open_url)

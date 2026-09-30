"""Palette actions that load the open design's model for the Publish Item panel.

The summary loads first. The rest loads only when the panel asks for it (a tab
opening, a component being clicked), each on its own worker thread.
"""

import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

from ...auth.auth_service import AuthService
from ...auth.errors import AuthError
from ...config.config_service import ConfigService
from ...config.workspace_models import WorkspaceConfig
from ...core.logging_setup import get_logger
from ...fm.bom import BomService
from ...fm.client import FmApiError, FmClient
from ...fm.items import ItemService
from ...fusion_mfg.graphql_client import MfgGraphQlClient
from ...fusion_mfg.model_service import SECTION_NAMES, read_section
from ...sync.bom_compare import compare_bom
from ...sync.property_compare import FOUND, MULTIPLE, NEW, UNKNOWN, compare_properties
from ..message_bridge import MessageBridge

log = get_logger("publish_actions")

ITEMS_KIND = "items"
VALIDATION_WORKERS = 5   # Fusion Manage searches in flight at once

def _compare(properties: List[Dict[str, str]], summary: Dict[str, Any], cfg: WorkspaceConfig,
             fm: FmClient, chosen: str = "") -> Dict[str, Any]:
    """Compare the properties with Fusion Manage. Runs on a worker thread.

    The item is searched by item number in the Items workspace. When several
    items match, ``chosen`` (an item id the user picked) selects one; until then
    the state is ``multiple`` and ``candidates`` lists them.
    """
    mappings = [m for m in cfg.mappings if m.source and m.fm_field_id]
    number = str(summary.get("item_number") or summary.get("part_number") or "").strip()
    info: Dict[str, Any] = {"state": "unchecked", "message": "", "item_id": "", "item_number": number,
                            "candidates": []}
    fm_fields = None
    if not cfg.workspace_id:
        info["message"] = "Set the Items workspace ID in Settings to compare with Fusion Manage."
    elif not number:
        info["message"] = "This component has no item number to look up in Fusion Manage."
    else:
        try:
            service = ItemService(fm)
            hits = service.search(cfg.workspace_id, number)
            picked = next((h for h in hits if h["id"] == chosen), None) or (hits[0] if len(hits) == 1 else None)
            if picked:
                fm_fields = service.read(cfg.workspace_id, picked["id"])
        except (FmApiError, AuthError) as exc:
            log.warning("Fusion Manage lookup failed: %s", exc)
            info.update(state=UNKNOWN, message=f"Could not read Fusion Manage: {exc}")
        else:
            if not hits:
                info.update(state=NEW)
            else:
                info["candidates"] = hits if len(hits) > 1 else []
                if picked:
                    info.update(state=FOUND, item_id=picked["id"])
                else:
                    info.update(state=MULTIPLE, message=f"{len(hits)} Fusion Manage items match {number}. Choose one.")
    return {"fm": info,
            "rows": compare_properties(properties, summary, mappings, fm_fields, info["state"])}


def _compare_bom(rows: List[Dict[str, Any]], summary: Dict[str, Any], cfg: WorkspaceConfig,
                 fm: FmClient, chosen: str = "") -> Dict[str, Any]:
    """Mark each BOM row against the Fusion Manage BOM of the open design. Runs on a worker thread.

    One BOM call, deep enough for the whole tree, covers every assembly. Rows stay
    unchecked (no status) when Fusion Manage cannot be read. When the design matches
    several items and none is chosen, ``pick`` is set and the panel waits for the choice.
    """
    number = str(summary.get("item_number") or summary.get("part_number") or "").strip()
    if not cfg or not cfg.workspace_id or not number:
        return {"rows": rows, "pick": False}
    try:
        service = ItemService(fm)
        hits = service.search(cfg.workspace_id, number)
        if not hits:
            return {"rows": compare_bom(rows, number, {}), "pick": False}   # the design is new, so every line is
        picked = next((h for h in hits if h["id"] == chosen), None) or (hits[0] if len(hits) == 1 else None)
        if not picked:
            return {"rows": rows, "pick": True}
        depth = max([int(r["level"]) for r in rows] + [0]) + 1
        fm_bom = BomService(fm).read(cfg.workspace_id, picked["id"], depth)
        log.info("Fusion Manage BOM of %s: %d parent(s), %d line(s)", number, len(fm_bom),
                 sum(len(v) for v in fm_bom.values()))
        return {"rows": compare_bom(rows, number, fm_bom), "pick": False}
    except (FmApiError, AuthError) as exc:
        log.warning("Fusion Manage BOM lookup failed: %s", exc)
        return {"rows": rows, "pick": False}


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
    entry: Dict[str, Any] = {"section": section, "pending": False, "ok": False, "data": None, "message": "", "key": ""}
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
            with lock:
                summary = dict(sections["summary"]["data"] or {}) if sections["summary"]["key"] == key else {}
            data = read_section(client, name, model_id, time, summary, component.get("id", ""))
            if name == "properties":
                data = {"count": len(data), "compare": _compare(data, summary, cfg, fm, chosen)}
            elif name == "structure":
                data = _compare_bom(data, summary, cfg, fm, chosen)
            elif name == "component":
                data = {"compare": _compare(data["properties"], component, cfg, fm, chosen), "drawings": data["drawings"]}
            log.info("Loaded %s of %s", slot, model_id)
            outcome = _entry(slot, ok=True, data=data, key=key)
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
                return dict(current)
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
        """Open a link in the system browser (a palette cannot open one itself). https only."""
        url = str(payload.get("url", ""))
        if not url.lower().startswith("https://"):
            raise ValueError("Only https links can be opened.")
        webbrowser.open(url)
        return {}

    # One search per distinct item number, so the panel can flag new and duplicated items up front.
    validation: Dict[str, Any] = {"key": "", "running": False, "done": 0, "total": 0, "results": {}, "message": ""}

    def check_number(service: ItemService, workspace_id: str, number: str) -> Dict[str, Any]:
        try:
            hits = service.search(workspace_id, number)
        except (FmApiError, AuthError) as exc:
            return {"state": UNKNOWN, "candidates": [], "message": str(exc)}
        state = NEW if not hits else (FOUND if len(hits) == 1 else MULTIPLE)
        return {"state": state, "candidates": hits if len(hits) > 1 else [], "message": ""}

    def validate(key: str, numbers: List[str], fm: FmClient, workspace_id: str) -> None:
        service = ItemService(fm)

        def record(number: str, result: Dict[str, Any]) -> None:
            with lock:
                if validation["key"] == key:   # ignore a run for a design that is no longer open
                    validation["results"][number] = result
                    validation["done"] += 1

        try:
            if numbers:   # first search alone, so any token refresh happens once before the parallel ones
                record(numbers[0], check_number(service, workspace_id, numbers[0]))
            with ThreadPoolExecutor(max_workers=VALIDATION_WORKERS) as pool:
                futures = {pool.submit(check_number, service, workspace_id, n): n for n in numbers[1:]}
                for future in as_completed(futures):
                    record(futures[future], future.result())
        except Exception as exc:  # never leave the panel waiting
            log.exception("Validating Fusion Manage items failed")
            with lock:
                validation["message"] = str(exc) or type(exc).__name__
        with lock:
            if validation["key"] == key:
                validation["running"] = False
        log.info("Validated %d item number(s) against Fusion Manage", len(numbers))

    def start_fm_validation(payload: Dict[str, Any]) -> Dict[str, Any]:
        numbers = list(dict.fromkeys(str(n).strip() for n in payload.get("numbers") or [] if str(n).strip()))
        model_id, time = _model_ref()
        key = f"{model_id}|{time}"
        cfg = config.config.workspaces.get(ITEMS_KIND)
        with lock:
            if validation["key"] == key and (validation["running"] or validation["done"]) and not payload.get("force"):
                return dict(validation)
            validation.update(key=key, running=False, done=0, total=0, results={}, message="")
            if not model_id or not cfg or not cfg.workspace_id:
                return dict(validation)
            validation.update(running=True, total=len(numbers))
            snapshot = dict(validation)
        fm = FmClient(config.effective_settings(), auth)
        threading.Thread(target=validate, args=(key, numbers, fm, cfg.workspace_id), daemon=True).start()
        return snapshot

    def get_fm_validation(_payload: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            return dict(validation)

    def get_publish_model_key(_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Cheap check of which design is open, so the panel reloads only on a change."""
        model_id, time = _model_ref()
        return {"key": f"{model_id}|{time}" if model_id else ""}

    bridge.register("load_publish_section", load_publish_section)
    bridge.register("load_publish_section_status", load_publish_section_status)
    bridge.register("get_publish_model_key", get_publish_model_key)
    bridge.register("open_url", open_url)
    bridge.register("start_fm_validation", start_fm_validation)
    bridge.register("get_fm_validation", get_fm_validation)

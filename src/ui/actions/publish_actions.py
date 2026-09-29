"""Palette actions that load the open design's model for the Publish Item panel.

The summary loads first. The rest loads only when the panel asks for it (a tab
opening, a component being clicked), each on its own worker thread.
"""

import threading
import webbrowser
from typing import Any, Dict, List, Tuple

from ...auth.auth_service import AuthService
from ...auth.errors import AuthError
from ...config.config_service import ConfigService
from ...config.workspace_models import WorkspaceConfig
from ...core.logging_setup import get_logger
from ...fm.client import FmApiError, FmClient
from ...fm.items import ItemService
from ...fusion_mfg.graphql_client import MfgGraphQlClient
from ...fusion_mfg.model_service import SECTION_NAMES, read_section
from ...sync.property_compare import FOUND, compare_properties, source_value
from ..message_bridge import MessageBridge

log = get_logger("publish_actions")

ITEMS_KIND = "items"

# The Fusion Manage item search is not built yet; until it is, the comparison
# column shows "-" and no lookup is made.
FM_LOOKUP_ENABLED = False


def _compare(properties: List[Dict[str, str]], summary: Dict[str, Any],
             cfg: WorkspaceConfig, fm: FmClient) -> Dict[str, Any]:
    """Compare the properties with Fusion Manage. Runs on a worker thread."""
    mappings = [m for m in cfg.mappings if m.source and m.fm_field_id]
    key = next((m for m in mappings if m.match_key), None)
    info: Dict[str, Any] = {"state": "unchecked" if not FM_LOOKUP_ENABLED else "unknown", "message": "", "item_id": ""}
    fm_fields = None
    if not FM_LOOKUP_ENABLED:
        pass
    elif not cfg.workspace_id:
        info["message"] = "Set the Items workspace ID in Settings to compare with Fusion Manage."
    elif key is None:
        info["message"] = "Mark one field mapping as the match key in Settings to find the Fusion Manage item."
    else:
        values = {p["name"].strip().lower(): p["value"] for p in properties}
        match_value = source_value(key.source, summary, values)
        try:
            item = ItemService(fm).find(cfg.workspace_id, key.fm_field_id, match_value)
        except (FmApiError, AuthError) as exc:
            log.warning("Fusion Manage lookup failed: %s", exc)
            info["message"] = f"Could not read Fusion Manage: {exc}"
        else:
            if item:
                info.update(state=FOUND, item_id=item["id"], message="Found in Fusion Manage.")
                fm_fields = item["fields"]
            else:
                info.update(state="new", message="Not in Fusion Manage yet. Publishing will create it.")
    return {"fm": info,
            "rows": compare_properties(properties, summary, mappings, fm_fields, info["state"])}


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
            model_id: str, time: str, component: Dict[str, str]) -> None:
        try:
            with lock:
                summary = dict(sections["summary"]["data"] or {}) if sections["summary"]["key"] == key else {}
            data = read_section(client, name, model_id, time, summary, component.get("id", ""))
            if name == "properties":
                data = {"count": len(data), "compare": _compare(data, summary, cfg, fm)}
            elif name == "component":
                data = {"compare": _compare(data["properties"], component, cfg, fm), "drawings": data["drawings"]}
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
        threading.Thread(target=run, args=(slot, name, key, client, fm, cfg, model_id, time, component),
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

    def get_publish_model_key(_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Cheap check of which design is open, so the panel reloads only on a change."""
        model_id, time = _model_ref()
        return {"key": f"{model_id}|{time}" if model_id else ""}

    bridge.register("load_publish_section", load_publish_section)
    bridge.register("load_publish_section_status", load_publish_section_status)
    bridge.register("get_publish_model_key", get_publish_model_key)
    bridge.register("open_url", open_url)

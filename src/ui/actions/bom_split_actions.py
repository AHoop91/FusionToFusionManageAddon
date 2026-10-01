"""Palette actions for the Bill of Materials tab.

While the tab is in development this holds a probe: the Manufacturing Data Model
schema is searched for fields that could mark a component as hidden or excluded
from the BOM, and the matches are written to the log. Once the right field is
known it goes into the structure query and the probe is removed.
"""

import re
import threading
from typing import Any, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...core.logging_setup import get_logger
from ...fusion_mfg.graphql_client import MfgGraphQlClient
from ..message_bridge import MessageBridge

log = get_logger("bom_split")

TYPE_REF = "name kind ofType { name kind ofType { name kind ofType { name kind } } }"
SCHEMA_QUERY = ("{ __schema { types { name kind possibleTypes { name } enumValues { name } "
                "fields { name type { " + TYPE_REF + " } } } } }")
_INTERESTING = re.compile(r"hidden|exclu|visib|suppress|bomstatus|lightbulb", re.IGNORECASE)


def _named(ref: Any) -> str:
    """Name of a (possibly wrapped) GraphQL type reference."""
    while isinstance(ref, dict) and not ref.get("name") and ref.get("ofType"):
        ref = ref["ofType"]
    return str((ref or {}).get("name") or "")


def find_candidates(data: Dict[str, Any]) -> Dict[str, list]:
    """What decides where a hidden or excluded flag can be read from the BOM relations.

    Keys are log labels, values the lines to log: field names that hint at it, the relation
    type behind ``Component.bomRelations``, and the types that carry a Visibility.
    """
    types = {str(t.get("name")): t for t in (data.get("__schema") or {}).get("types") or []}
    found: Dict[str, list] = {}
    for name, entry in types.items():
        names = [f.get("name", "") for f in entry.get("fields") or [] if _INTERESTING.search(f.get("name", ""))]
        if names:
            found[name] = names

    def fields_of(type_name: str) -> list:
        return [f"{f['name']}: {_named(f.get('type'))}" for f in (types.get(type_name) or {}).get("fields") or []]

    relation = next((f for f in (types.get("Component") or {}).get("fields") or [] if f.get("name") == "bomRelations"), None)
    if relation:
        page = _named(relation.get("type"))
        found["bomRelations returns " + page] = fields_of(page)
        results = next((f for f in (types.get(page) or {}).get("fields") or [] if f.get("name") == "results"), None)
        result_type = _named((results or {}).get("type"))
        found["bomRelations results are " + result_type] = fields_of(result_type) or [
            "possible: " + ", ".join(t["name"] for t in (types.get(result_type) or {}).get("possibleTypes") or [])]
    for name, entry in types.items():
        for f in entry.get("fields") or []:
            if _named(f.get("type")) == "Visibility":
                found["carries Visibility: " + name] = [f["name"]]
            if _INTERESTING.search(f.get("name", "")) and "xclusion" in f.get("name", ""):
                reason = _named(f.get("type"))
                found[f"{name}.{f['name']} is {reason}"] = [v["name"] for v in (types.get(reason) or {}).get("enumValues") or []] or fields_of(reason)
    return found


def register_bom_split_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the probe. It runs once per session, on a worker thread."""
    state = {"started": False}

    def probe(client: MfgGraphQlClient) -> None:
        try:
            found = find_candidates(client.query(SCHEMA_QUERY))
            for type_name, names in sorted(found.items()):
                log.info("Schema candidate %s: %s", type_name, ", ".join(names))
            log.info("Schema probe done: %d type(s) with hidden/excluded-like fields", len(found))
        except Exception:  # a probe must never disturb the panel
            log.exception("Schema probe failed")

    def probe_hidden_fields(_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not state["started"]:
            state["started"] = True
            client = MfgGraphQlClient(config.effective_settings(), auth)
            threading.Thread(target=probe, args=(client,), daemon=True).start()
        return {}

    bridge.register("probe_hidden_fields", probe_hidden_fields)

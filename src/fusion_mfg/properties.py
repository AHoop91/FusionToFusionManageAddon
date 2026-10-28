"""Property definitions of a Manufacturing Data Model hub.

Definitions are per hub. Base properties ship with the Data Model; custom
properties come from collections an admin linked to the hub. Both apply to
the items the add-in reads.
"""

from typing import Any, Dict, List

from ..config.workspace_models import PHYSICAL_NAMES
from .fusion_graphql_client import FusionGraphQlClient, MfgApiError

BASE = "base"
CUSTOM = "custom"
PHYSICAL = "physical"

# Every hub the user can see: a hub is found by name (``find_hub_id``), whichever of the add-in's reads needs its id.
HUBS_QUERY = "query Hubs { hubs { results { id name } } }"

DEFINITIONS_QUERY = """
query HubProperties($hubId: ID!) {
  hub(hubId: $hubId) {
    basePropertyDefinitionCollections { ...propertyCollections }
    propertyDefinitionCollections { ...propertyCollections }
  }
}

fragment propertyCollections on PropertyDefinitionCollections {
  results {
    name
    definitions(pagination: { limit: 100 }) {
      results { name specification isHidden isArchived applicableEntityTypes }
    }
  }
}
"""


def find_hub_id(data: Dict[str, Any], hub_name: str) -> str:
    """Pick the hub matching ``hub_name`` (or the only hub) from a ``hubs`` result."""
    hubs = [h for h in ((data.get("hubs") or {}).get("results") or []) if isinstance(h, dict)]
    for hub in hubs:
        if hub_name and str(hub.get("name", "")).strip().lower() == hub_name.strip().lower():
            return str(hub.get("id", ""))
    if len(hubs) == 1:
        return str(hubs[0].get("id", ""))
    raise MfgApiError(f"Could not find hub '{hub_name}' in the Manufacturing Data Model.")


def _visible(collections: Any, group: str) -> Dict[str, Dict[str, Any]]:
    """Usable item (component) properties of one group, keyed by name."""
    found: Dict[str, Dict[str, Any]] = {}
    for collection in (collections or {}).get("results") or []:
        for d in ((collection or {}).get("definitions") or {}).get("results") or []:
            if not isinstance(d, dict) or d.get("isHidden") or d.get("isArchived") or not d.get("name"):
                continue
            types = d.get("applicableEntityTypes") or []
            if types and "COMPONENT" not in types:
                continue
            found[d["name"]] = {"name": d["name"], "group": group,
                                "specification": str(d.get("specification", ""))}
    return found


def parse_definitions(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Base then custom properties, each sorted by name."""
    hub = data.get("hub") or {}
    result: List[Dict[str, Any]] = []
    for key, group in (("basePropertyDefinitionCollections", BASE), ("propertyDefinitionCollections", CUSTOM)):
        found = _visible(hub.get(key), group)
        result += sorted(found.values(), key=lambda p: p["name"].lower())
    return result + [{"name": n, "group": PHYSICAL, "specification": ""} for n in PHYSICAL_NAMES]   # every component has them


class PropertyService:
    """Lists the properties available in a hub."""

    def __init__(self, client: FusionGraphQlClient) -> None:
        self._client = client

    def list_properties(self, hub_name: str) -> List[Dict[str, Any]]:
        hub_id = find_hub_id(self._client.query(HUBS_QUERY), hub_name)
        return parse_definitions(self._client.query(DEFINITIONS_QUERY, {"hubId": hub_id}))

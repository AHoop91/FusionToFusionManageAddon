"""Property definitions of a Manufacturing Data Model hub.

Definitions are per hub. Base properties ship with the Data Model; custom properties come from collections an admin linked to the hub. Both
apply to the items the add-in reads.
"""

from typing import Any, Dict, List

from ..config.workspace_models import PHYSICAL_NAMES
from ..core.shapes import as_dict, as_list, dict_rows, dig
from .fusion_graphql_client import FusionGraphQlClient
from .hub_lookup import read_hub_id

BASE = "base"
CUSTOM = "custom"
PHYSICAL = "physical"
COMPONENT = "COMPONENT"   # the entity type of the items the add-in reads
COLLECTIONS = (("basePropertyDefinitionCollections", BASE), ("propertyDefinitionCollections", CUSTOM))   # where each group is in the answer

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


def _usable(definition: Dict[str, Any]) -> bool:
    """Whether a property definition is one to offer: not hidden or archived, named, and for components (or for every entity type)."""
    if definition.get("isHidden") or definition.get("isArchived") or not definition.get("name"):
        return False
    types = as_list(definition.get("applicableEntityTypes"))
    return not types or COMPONENT in types


def _visible(collections: Any, group: str) -> List[Dict[str, Any]]:
    """The usable properties of one group, by name; a name a later collection repeats is that collection's."""
    found: Dict[str, Dict[str, Any]] = {}
    for collection in dict_rows(dig(collections, "results")):
        for definition in dict_rows(dig(collection, "definitions", "results")):
            if _usable(definition):
                found[definition["name"]] = {"name": definition["name"], "group": group, "specification": str(definition.get("specification") or "")}
    return sorted(found.values(), key=lambda prop: prop["name"].lower())


def parse_definitions(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The properties of a ``DEFINITIONS_QUERY`` answer as ``{"name", "group", "specification"}``: base, then custom (each by name), then the
    physical ones, which every component has."""
    hub = as_dict(dig(data, "hub"))
    result: List[Dict[str, Any]] = []
    for key, group in COLLECTIONS:
        result += _visible(hub.get(key), group)
    return result + [{"name": name, "group": PHYSICAL, "specification": ""} for name in PHYSICAL_NAMES]


class PropertyService:
    """Lists the properties available in a hub."""

    def __init__(self, client: FusionGraphQlClient) -> None:
        self._client = client

    def list_properties(self, hub_name: str) -> List[Dict[str, Any]]:
        """The properties of the hub called ``hub_name`` (see ``parse_definitions``). Raises ``MfgApiError`` when they cannot be read."""
        return parse_definitions(self._client.query(DEFINITIONS_QUERY, {"hubId": read_hub_id(self._client, hub_name)}))

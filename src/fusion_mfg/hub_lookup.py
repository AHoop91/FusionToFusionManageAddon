"""Finding a hub in the Manufacturing Data Model by its name, whichever of the add-in's reads needs the hub's id."""

from typing import Any, Dict

from ..core.shapes import dict_rows, dig
from .fusion_graphql_client import FusionGraphQlClient, MfgApiError

# Every hub the user can see.
HUBS_QUERY = "query Hubs { hubs { results { id name } } }"


def _same(a: Any, b: Any) -> bool:
    """Whether two hub names are the same: ignoring case and surrounding space."""
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def find_hub_id(data: Dict[str, Any], hub_name: str) -> str:
    """The id of the hub called ``hub_name`` (or of the only hub, when the name matches none) in a ``HUBS_QUERY`` answer.

    Raises ``MfgApiError`` when no single hub can be told."""
    hubs = dict_rows(dig(data, "hubs", "results"))
    named = next((hub for hub in hubs if hub_name and _same(hub.get("name"), hub_name)), None)
    if named is None and len(hubs) == 1:
        named = hubs[0]
    if named is None:
        raise MfgApiError(f"Could not find hub '{hub_name}' in the Manufacturing Data Model.")
    return str(named.get("id") or "")


def read_hub_id(client: FusionGraphQlClient, hub_name: str) -> str:
    """Ask the Data Model for the id of the hub called ``hub_name``. Slow (a network call): not on Fusion's thread."""
    return find_hub_id(client.query(HUBS_QUERY), hub_name)

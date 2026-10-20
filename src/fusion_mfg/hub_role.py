"""The signed-in user's role in a hub, from the Manufacturing Data Model.

Only a Hub Admin may read a hub's members: for anyone else the service answers ``FHQ-403`` (access denied). That refusal is therefore
an answer, "not an admin"; anything else that goes wrong (the network, the service) says nothing about the role.
"""

from typing import Any, Dict, NamedTuple

from ..auth.errors import AuthError
from .graphql_client import MfgApiError, MfgGraphQlClient

ROLE_ADMIN = "ADMIN"
ACCESS_DENIED = "FHQ-403"

HUB_ROLE_QUERY = """
query GetMyHubRole($hubId: ID!, $email: String!) {
  hub(hubId: $hubId) {
    members(filter: { name: $email }) {
      results {
        user { id email }
        role
        status
      }
    }
  }
}
"""


class HubRole(NamedTuple):
    """What is known of the user's role in a hub."""

    admin: bool
    known: bool   # False when the question could not be answered; such an answer is not kept
    role: str = ""


UNKNOWN = HubRole(admin=False, known=False)
NOT_ADMIN = HubRole(admin=False, known=True)


def parse_hub_role(data: Dict[str, Any], email: str) -> HubRole:
    """The role of ``email`` in a ``HUB_ROLE_QUERY`` answer. The filter matches on names, so only the row of exactly this email counts."""
    members = ((data.get("hub") or {}).get("members") or {}).get("results") or []
    mine = [m for m in members if isinstance(m, dict) and str((m.get("user") or {}).get("email", "")).strip().lower() == email.strip().lower()]
    if len(mine) != 1:
        return UNKNOWN   # not found, or not told apart
    role = str(mine[0].get("role") or "")
    return HubRole(admin=role == ROLE_ADMIN, known=True, role=role)


def read_hub_role(client: MfgGraphQlClient, hub_id: str, email: str) -> HubRole:
    """Ask the Data Model for the role of ``email`` in the hub ``hub_id``. Slow (a network call): not on Fusion's thread."""
    if not hub_id or not email.strip():
        return UNKNOWN
    try:
        return parse_hub_role(client.query(HUB_ROLE_QUERY, {"hubId": hub_id, "email": email.strip()}, "hub role"), email)
    except MfgApiError as exc:
        return NOT_ADMIN if exc.code == ACCESS_DENIED else UNKNOWN
    except AuthError:
        return UNKNOWN   # not signed in

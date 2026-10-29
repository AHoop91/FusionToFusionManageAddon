"""The signed-in user's role in a hub, from the Manufacturing Data Model.

Only a Hub Admin may read a hub's members: for anyone else the service answers ``FHQ-403`` (access denied). That refusal is therefore
an answer, "not an admin"; anything else that goes wrong (the network, the service) says nothing about the role.
"""

from typing import Any, Dict, NamedTuple

from ..core.shapes import as_list, dig
from .fusion_graphql_client import FusionGraphQlClient, MfgApiError

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


def _normal(email: Any) -> str:
    """``email`` as it is compared: trimmed, in lower case."""
    return str(email or "").strip().lower()


def parse_hub_role(data: Dict[str, Any], email: str) -> HubRole:
    """The role of ``email`` in a ``HUB_ROLE_QUERY`` answer. The filter matches on names, so only the row of exactly this email counts."""
    members = dig(data, "hub", "members", "results")
    wanted = _normal(email)
    mine = [member for member in as_list(members) if _normal(dig(member, "user", "email")) == wanted]
    if len(mine) != 1:
        return UNKNOWN   # not found, or not told apart
    role = str(dig(mine[0], "role") or "")
    return HubRole(admin=role == ROLE_ADMIN, known=True, role=role)


def read_hub_role(client: FusionGraphQlClient, hub_id: str, email: str) -> HubRole:
    """Ask the Data Model for the role of ``email`` in the hub ``hub_id``. Slow (a network call): not on Fusion's thread."""
    email = email.strip()
    if not hub_id or not email:
        return UNKNOWN
    try:
        return parse_hub_role(client.query(HUB_ROLE_QUERY, {"hubId": hub_id, "email": email}, "hub role"), email)
    except MfgApiError as exc:
        return NOT_ADMIN if exc.code == ACCESS_DENIED else UNKNOWN   # a refusal is the answer; any other failure says nothing

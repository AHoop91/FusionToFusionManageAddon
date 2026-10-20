"""Current-user profile from the Autodesk user profile API.

``GET /userinfo`` (scope ``user-profile:read``) returns the signed-in user, including a ``picture`` link. It needs no Fusion Manage
tenant, so the avatar can show before one is set. The link points at Autodesk's public profile image host, so the panel loads it
directly.
"""

import json
import urllib.request
from typing import Any, Dict

from ..auth.errors import AuthError
from ..core.http import open_url
from ..core.logging_setup import get_logger
from .client import REQUEST_TIMEOUT_SECONDS, FmClient

log = get_logger("fm.profile")

USERINFO_URL = "https://api.userprofile.autodesk.com/userinfo"   # a fixed host: the access token goes nowhere else


def parse_userinfo(data: Dict[str, Any], tenant: str) -> Dict[str, Any]:
    """The panel's profile from an Autodesk ``/userinfo`` answer."""
    name = data.get("name") or " ".join(p for p in (data.get("given_name"), data.get("family_name")) if p)
    picture = FmClient.https_only(data.get("picture"))
    return {"name": name or "", "email": data.get("email", ""), "picture": picture, "picture_large": picture,
            "tenant": tenant, "user_id": str(data.get("sub") or "")}


class ProfileService:
    """Reads the signed-in user's profile with the access token of an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def empty(self) -> Dict[str, Any]:
        """Profile with no data; the panel shows a generic avatar for it."""
        return {"name": "", "email": "", "picture": "", "picture_large": "",
                "tenant": self._client.tenant, "user_id": ""}

    def current(self) -> Dict[str, Any]:
        """Return the user's name, email, avatar URL, tenant and id.

        Failure is non-fatal: values are empty and the panel falls back to a generic avatar.
        """
        try:
            request = urllib.request.Request(USERINFO_URL, headers={"Accept": "application/json", "Authorization": f"Bearer {self._client.access_token()}"})
            with open_url(request, REQUEST_TIMEOUT_SECONDS, self._client.cancel) as response:
                data = json.loads(response.read())
            if not isinstance(data, dict):
                raise ValueError("unexpected user profile")
        except (AuthError, OSError, ValueError) as exc:   # OSError: the network, or a refusal such as 403 for a sign-in without the scope
            log.warning("Could not load the Autodesk user profile: %s", exc)
            return self.empty()
        return parse_userinfo(data, self._client.tenant)

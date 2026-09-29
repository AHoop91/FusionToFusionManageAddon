"""Current-user profile from the Fusion Manage REST API.

``GET /api/v3/users/@me`` returns the signed-in user, including
``image.small|medium|large`` links. The links point at Autodesk's public
profile image host, so the panel loads them directly.
"""

from typing import Any, Dict

from ..auth.errors import AuthError
from ..core.logging_setup import get_logger
from .client import FmApiError, FmClient

log = get_logger("fm.profile")

PROFILE_PATH = "/api/v3/users/@me"


class ProfileService:
    """Reads the signed-in user's profile through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def empty(self) -> Dict[str, Any]:
        """Profile with no data; the panel shows a generic avatar for it."""
        return {"name": "", "email": "", "picture": "", "picture_large": "",
                "tenant": self._client.tenant, "user_id": ""}

    def current(self) -> Dict[str, Any]:
        """Return the user's name, email, avatar URLs, tenant and id.

        Failure is non-fatal: values are empty and the panel falls back to a
        generic avatar.
        """
        try:
            data = self._client.get_json(PROFILE_PATH)
        except (AuthError, FmApiError) as exc:
            log.warning("Could not load Fusion Manage user profile: %s", exc)
            return self.empty()

        https_only = self._client.https_only
        name = data.get("displayName") or " ".join(
            p for p in (data.get("firstName"), data.get("lastName")) if p)
        image = data.get("image") or {}
        return {
            "name": name or "",
            "email": data.get("email", ""),
            # Header avatar is small on screen; the account card shows a bigger
            # one, so prefer the largest image there to avoid pixelation.
            "picture": https_only(image.get("medium") or image.get("small") or image.get("large")),
            "picture_large": https_only(image.get("large") or image.get("medium") or image.get("small")),
            "tenant": self._client.tenant,
            "user_id": str(data.get("userId") or data.get("id") or ""),
        }

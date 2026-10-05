"""Fusion Manage REST client.

Single place that knows how to address a tenant and make authenticated calls.
Feature classes (profile today; items, BOMs and files later) take an
``FmClient`` instead of building URLs and headers themselves.
"""

import json
import urllib.error
import urllib.request
from typing import Any

from ..auth.auth_service import AuthService
from ..config.models import ConnectionSettings
from ..core.logging_setup import get_logger

log = get_logger("fm.client")

FM_HOST_SUFFIX =".autodeskplm360.net"
REQUEST_TIMEOUT_SECONDS = 15

# Path roots of the REST API, shared by every feature that builds a url.
WORKSPACES = "/api/v3/workspaces"
LOOKUPS = "/api/v3/lookups"


def last_segment(link: Any) -> str:
    """The id at the end of a link such as ``/api/v3/workspaces/242/views/1/fields/TITLE`` ("" if not text)."""
    return link.rstrip("/").rsplit("/", 1)[-1] if isinstance(link, str) else ""


class FmApiError(Exception):
    """Raised when a Fusion Manage request fails or returns bad data."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status   # HTTP status, or 0 when there was no response


class FmClient:
    """Authenticated access to one Fusion Manage tenant."""

    def __init__(self, settings: ConnectionSettings, auth: AuthService) -> None:
        self._settings = settings
        self._auth = auth

    @property
    def tenant(self) -> str:
        return self._settings.tenant.strip()

    @property
    def base_url(self) -> str:
        """API root, e.g. https://acme.autodeskplm360.net."""
        return f"https://{self.tenant}{FM_HOST_SUFFIX}"

    @staticmethod
    def https_only(url: Any) -> str:
        """Accept only https links so a bad response cannot inject other schemes."""
        return url if isinstance(url, str) and url.lower().startswith("https://") else ""

    def get_json(self, path: str, accept: str = "application/json") -> Any:
        """GET ``path`` (e.g. ``/api/v3/users/@me``) and return parsed JSON.

        Raises ``AuthError`` if there is no valid session and ``FmApiError``
        for network, HTTP or parsing failures. The access token is fetched per
        call so an expired one is refreshed transparently.
        """
        token = self._auth.get_access_token(self._settings)
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Accept": accept, "Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read()
                if response.status == 204 or not body.strip():   # no content, e.g. a search with no hits
                    return None
                try:
                    return json.loads(body)
                except ValueError:
                    log.error("Fusion Manage HTTP %s for %s was not JSON (%s): %r", response.status, path,
                              response.headers.get("Content-Type"), body[:300])
                    raise
        except urllib.error.HTTPError as exc:
            log.error("Fusion Manage HTTP %s for %s: %s", exc.code, path,
                      exc.read()[:1000].decode("utf-8", "replace"))
            raise FmApiError(f"Fusion Manage returned {exc.code} for {path}", exc.code) from exc
        except (OSError, ValueError) as exc:
            raise FmApiError(f"Fusion Manage request failed for {path}: {exc}") from exc

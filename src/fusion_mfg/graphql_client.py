"""Manufacturing Data Model GraphQL client.

Uses the same signed-in APS session as Fusion Manage (the ``data:read`` scope
covers both), so no second login is needed.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..auth.auth_service import AuthService
from ..config.models import ConnectionSettings
from ..core.logging_setup import get_logger

log = get_logger("graphql")

GRAPHQL_URL = "https://developer.api.autodesk.com/mfg/v3/graphql"
REQUEST_TIMEOUT_SECONDS = 45


class MfgApiError(Exception):
    """Raised when a Manufacturing Data Model request fails or returns errors."""


class MfgGraphQlClient:
    """Authenticated GraphQL access to the Manufacturing Data Model."""

    def __init__(self, settings: ConnectionSettings, auth: AuthService) -> None:
        self._settings = settings
        self._auth = auth

    def query(self, text: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run a query and return its ``data`` object.

        Raises ``AuthError`` without a valid session and ``MfgApiError`` for
        network, HTTP or GraphQL errors.
        """
        token = self._auth.get_access_token(self._settings)
        body = json.dumps({"query": text, "variables": variables or {}}).encode("utf-8")
        request = urllib.request.Request(GRAPHQL_URL, data=body, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:4000].decode("utf-8", "replace")
            log.error("GraphQL HTTP %s from %s: %s", exc.code, GRAPHQL_URL, detail)
            try:
                reason = str(json.loads(detail)["errors"][0]["message"])[:200]
            except (ValueError, KeyError, IndexError, TypeError):
                reason = ""
            raise MfgApiError(f"Manufacturing Data Model returned {exc.code}" + (f": {reason}" if reason else "")) from exc
        except (OSError, ValueError) as exc:
            raise MfgApiError(f"Manufacturing Data Model request failed: {exc}") from exc
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            log.error("GraphQL errors: %s", json.dumps(errors)[:1000])
            first = errors[0] if isinstance(errors[0], dict) else {}
            raise MfgApiError(str(first.get("message") or "GraphQL error"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise MfgApiError("Manufacturing Data Model returned no data.")
        return data

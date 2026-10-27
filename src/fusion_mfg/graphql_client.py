"""Manufacturing Data Model GraphQL client.

Uses the same signed-in APS session as Fusion Manage (the ``data:read`` scope
covers both), so no second login is needed.
"""

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..auth.auth_service import AuthService
from ..config.models import ConnectionSettings
from ..core.cancel import ADDIN, CancelToken
from ..core.http import open_url
from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch

log = get_logger("graphql")

GRAPHQL_URL = "https://developer.api.autodesk.com/mfg/v3/graphql"
REQUEST_TIMEOUT_SECONDS = 45
ATTEMPTS = 3
RETRY_SECONDS = 2   # wait before the second try, twice that before the third
RETRY_HTTP = (429, 502, 503, 504)
TRANSIENT_CODES = ("DATA_NOT_READY", "SUBREQUEST_HTTP_ERROR")   # a service behind the gateway was not ready or not answering


def _first_field(query_text: str) -> str:
    """The first field a query asks for (``component`` in ``query (...) { component(...) { ... } }``), to name it in the log."""
    match = re.search(r"\{\s*(\w+)", query_text)
    return match.group(1) if match else "query"


class MfgApiError(Exception):
    """Raised when a Manufacturing Data Model request fails or returns errors."""

    def __init__(self, message: str, transient: bool = False, code: str = "") -> None:
        super().__init__(message)
        self.transient = transient   # worth trying again: the service was busy or unreachable, not the query wrong
        self.code = code   # the service's own code for a GraphQL error (``FHQ-403``: not allowed), when it gave one


def data_of(payload: Any) -> Dict[str, Any]:
    """The ``data`` object of a GraphQL answer. Raises ``MfgApiError`` for the errors it reports, or when it has no data."""
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        log.error("GraphQL errors: %s", json.dumps(errors)[:1000])
        first = errors[0] if isinstance(errors[0], dict) else {}
        extensions = first.get("extensions") if isinstance(first.get("extensions"), dict) else {}
        transient = extensions.get("code") in TRANSIENT_CODES or (extensions.get("http") or {}).get("status") in RETRY_HTTP
        raise MfgApiError(str(first.get("message") or "GraphQL error"), transient=bool(transient), code=str(extensions.get("code") or ""))
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise MfgApiError("Manufacturing Data Model returned no data.")
    return data


class MfgGraphQlClient:
    """Authenticated GraphQL access to the Manufacturing Data Model."""

    def __init__(self, settings: ConnectionSettings, auth: AuthService, cancel: Optional[CancelToken] = None) -> None:
        self._settings = settings
        self._auth = auth
        self.cancel = cancel or ADDIN   # every request checks it, and is ended by it

    def query(self, text: str, variables: Optional[Dict[str, Any]] = None, label: str = "") -> Dict[str, Any]:
        """Run a query and return its ``data`` object.

        ``label`` names the query in the log (the first field it asks for when empty).
        Raises ``AuthError`` without a valid session and ``MfgApiError`` for
        network, HTTP or GraphQL errors. A query only reads, so one that failed
        because the service was busy or timed out is tried again a few times.
        """
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return self._query_once(text, variables, label)
            except MfgApiError as exc:
                if attempt == ATTEMPTS or not exc.transient:
                    raise
                log.warning("Manufacturing Data Model query failed (%s), attempt %d of %d", exc, attempt, ATTEMPTS)
                self.cancel.wait(RETRY_SECONDS * attempt)

    def _query_once(self, text: str, variables: Optional[Dict[str, Any]], label: str = "") -> Dict[str, Any]:
        watch = Stopwatch()
        token = self._auth.get_access_token(self._settings)
        token_seconds = watch.lap()
        body = json.dumps({"query": text, "variables": variables or {}}).encode("utf-8")
        request = urllib.request.Request(GRAPHQL_URL, data=body, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"})
        name = label or _first_field(text)
        try:
            with open_url(request, REQUEST_TIMEOUT_SECONDS, self.cancel) as response:
                first_byte_seconds = watch.lap()   # until the response headers arrived
                raw = response.read()
                payload = json.loads(raw)
            cost = payload.get("extensions") if isinstance(payload, dict) else None   # says what the query cost in points
            log.debug("graphql %s: token %.2fs, first byte %.2fs, download %.2fs, %d bytes%s", name, token_seconds,
                      first_byte_seconds, watch.lap(), len(raw), f", extensions {json.dumps(cost)[:300]}" if cost else "")
        except urllib.error.HTTPError as exc:
            log.debug("graphql %s failed with HTTP %s after %.2fs", name, exc.code, watch.lap())
            detail = exc.read()[:4000].decode("utf-8", "replace")
            log.error("GraphQL HTTP %s from %s: %s", exc.code, GRAPHQL_URL, detail)
            try:
                reason = str(json.loads(detail)["errors"][0]["message"])[:200]
            except (ValueError, KeyError, IndexError, TypeError):
                reason = ""
            raise MfgApiError(f"Manufacturing Data Model returned {exc.code}" + (f": {reason}" if reason else ""),
                              transient=exc.code in RETRY_HTTP) from exc
        except (OSError, ValueError) as exc:   # includes a timeout or a dropped connection
            raise MfgApiError(f"Manufacturing Data Model request failed: {exc}", transient=True) from exc
        return data_of(payload)

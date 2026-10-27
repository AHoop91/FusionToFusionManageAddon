"""Manufacturing Data Model GraphQL through Fusion itself (the ``mfgdm://`` address).

Fusion sends the request as the user it is signed in as, so no Client ID, sign-in or access token is needed. It answers like
``MfgGraphQlClient`` does (``query`` returns the ``data`` object, and raises ``MfgApiError``), so either can be used where one is wanted.
Fusion's HTTP call has been seen to work from a worker thread; use this from one, never from the UI's.
"""

import json
from typing import Any, Dict, Optional

from ..core.cancel import ADDIN, CancelToken
from ..core.logging_setup import get_logger
from .graphql_client import ATTEMPTS, RETRY_HTTP, RETRY_SECONDS, MfgApiError, data_of

log = get_logger("fusion_graphql")

FUSION_GRAPHQL_URL = "mfgdm://v3"


class FusionGraphQlClient:
    """GraphQL access to the Manufacturing Data Model with Fusion's own sign-in."""

    def __init__(self, cancel: Optional[CancelToken] = None) -> None:
        self.cancel = cancel or ADDIN

    def query(self, text: str, variables: Optional[Dict[str, Any]] = None, label: str = "") -> Dict[str, Any]:
        """Run a query and return its ``data`` object; one that failed because the service was busy is tried again a few times."""
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return self._query_once(text, variables)
            except MfgApiError as exc:
                if attempt == ATTEMPTS or not exc.transient:
                    raise
                log.warning("Manufacturing Data Model query failed (%s), attempt %d of %d", exc, attempt, ATTEMPTS)
                self.cancel.wait(RETRY_SECONDS * attempt)

    @staticmethod
    def _query_once(text: str, variables: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        import adsk.core   # only inside Fusion
        try:
            request = adsk.core.HttpRequest.create(FUSION_GRAPHQL_URL, adsk.core.HttpMethods.PostMethod)
            request.setHeader("Content-type", "application/json; charset=utf-8")
            request.data = json.dumps({"query": text, "variables": variables or {}})
            response = request.executeSync()
        except RuntimeError as exc:
            raise MfgApiError(f"Fusion could not send the request: {exc}", transient=True) from exc
        if response.statusCode != 200:
            raise MfgApiError(f"Manufacturing Data Model returned {response.statusCode}", transient=response.statusCode in RETRY_HTTP)
        try:
            payload = json.loads(response.data)
        except ValueError as exc:
            raise MfgApiError("Manufacturing Data Model returned an answer that was not understood.", transient=True) from exc
        return data_of(payload)

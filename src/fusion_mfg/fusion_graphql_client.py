"""Manufacturing Data Model GraphQL through Fusion itself (the ``mfgdm://`` address).

Fusion sends the request as the user it is signed in as, so no Client ID, sign-in or access token is needed. ``query`` returns the ``data``
object of the answer and raises ``MfgApiError`` for a failure.

The call waits on the network, so use it from a worker thread, never from Fusion's own (a warning is logged when it is).
"""

import json
import re
import threading
import time
from typing import Any, Dict, Optional

from ..core.cancel import ADDIN, CancelToken
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict
from ..core.timing import Stopwatch

log = get_logger("fusion_graphql")

FUSION_GRAPHQL_URL = "mfgdm://v3"
REQUEST_TIMEOUT_SECONDS = 45
POLL_SECONDS = 0.25   # how often a wait for an answer looks at the cancel token
ATTEMPTS = 3
RETRY_SECONDS = 2   # wait before the second try, twice that before the third
RETRY_HTTP = (429, 502, 503, 504)
TRANSIENT_CODES = ("DATA_NOT_READY", "SUBREQUEST_HTTP_ERROR")   # a service behind the gateway was not ready or not answering

# How much of an answer is kept in a log line or an error message.
HTTP_DETAIL_CHARS = 4000
ERRORS_LOG_CHARS = 1000
EXTENSIONS_LOG_CHARS = 300
REASON_CHARS = 200


def _first_field(query_text: str) -> str:
    """The first field a query asks for (``component`` in ``query (...) { component(...) { ... } }``), to name it in the log."""
    match = re.search(r"\{\s*(\w+)", query_text)
    return match.group(1) if match else "query"


def _text_of(response: Any) -> str:
    """What a failed response said, as text (empty when Fusion gave none)."""
    try:
        return str(response.data or "")
    except (RuntimeError, AttributeError):
        return ""


def _reason_in(detail: str) -> str:
    """The message of the first error a failed response reports, when it is a GraphQL answer (empty otherwise)."""
    try:
        return str(json.loads(detail)["errors"][0]["message"])[:REASON_CHARS]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


class MfgApiError(Exception):
    """Raised when a Manufacturing Data Model request fails or returns errors."""

    def __init__(self, message: str, transient: bool = False, code: str = "") -> None:
        super().__init__(message)
        self.transient = transient   # worth trying again: the service was busy or unreachable, not the query wrong
        self.code = code   # the service's own code for a GraphQL error (``FHQ-403``: not allowed), when it gave one


def data_of(payload: Any) -> Dict[str, Any]:
    """The ``data`` object of a GraphQL answer. Raises ``MfgApiError`` for the errors it reports, or when it has no data."""
    answer = as_dict(payload)
    errors = answer.get("errors")
    if errors:
        log.error("GraphQL errors: %s", json.dumps(errors)[:ERRORS_LOG_CHARS])
        first = as_dict(errors[0])
        extensions = as_dict(first.get("extensions"))
        status = as_dict(extensions.get("http")).get("status")
        transient = extensions.get("code") in TRANSIENT_CODES or status in RETRY_HTTP
        raise MfgApiError(str(first.get("message") or "GraphQL error"), transient=transient, code=str(extensions.get("code") or ""))
    data = answer.get("data")
    if not isinstance(data, dict):
        raise MfgApiError("Manufacturing Data Model returned no data.")
    return data


class FusionGraphQlClient:
    """GraphQL access to the Manufacturing Data Model with Fusion's own sign-in."""

    def __init__(self, cancel: Optional[CancelToken] = None) -> None:
        self.cancel = cancel or ADDIN   # every request checks it, and a wait for an answer is ended by it

    def with_cancel(self, cancel: CancelToken) -> "FusionGraphQlClient":
        """A client whose requests are checked and ended by ``cancel`` instead."""
        return FusionGraphQlClient(cancel)

    def query(self, text: str, variables: Optional[Dict[str, Any]] = None, label: str = "") -> Dict[str, Any]:
        """Run a query and return its ``data`` object.

        ``label`` names the query in the log (the first field it asks for when empty). A query only reads, so one that failed because the
        service was busy or timed out is tried again a few times. Raises ``Cancelled`` when the token is cancelled.
        """
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return self._query_once(text, variables, label)
            except MfgApiError as exc:
                if attempt == ATTEMPTS or not exc.transient:
                    raise
                log.warning("Manufacturing Data Model query failed (%s), attempt %d of %d", exc, attempt, ATTEMPTS)
                self.cancel.wait(RETRY_SECONDS * attempt)
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _query_once(self, text: str, variables: Optional[Dict[str, Any]], label: str) -> Dict[str, Any]:
        name = label or _first_field(text)
        if threading.current_thread() is threading.main_thread():
            log.warning("graphql %s was asked for on Fusion's own thread, which it blocks", name)
        watch = Stopwatch()
        response = self._execute(json.dumps({"query": text, "variables": variables or {}}))
        seconds = watch.lap()
        if response.statusCode != 200:
            log.debug("graphql %s failed with HTTP %s after %.2fs", name, response.statusCode, seconds)
            detail = _text_of(response)[:HTTP_DETAIL_CHARS]
            log.error("GraphQL HTTP %s from %s: %s", response.statusCode, FUSION_GRAPHQL_URL, detail)
            reason = _reason_in(detail)
            raise MfgApiError(f"Manufacturing Data Model returned {response.statusCode}" + (f": {reason}" if reason else ""),
                              transient=response.statusCode in RETRY_HTTP)
        try:
            payload = json.loads(response.data)
        except ValueError as exc:
            raise MfgApiError("Manufacturing Data Model returned an answer that was not understood.", transient=True) from exc
        cost = as_dict(payload).get("extensions")   # says what the query cost in points
        log.debug("graphql %s: %.2fs, %d bytes%s", name, seconds, len(response.data),
                  f", extensions {json.dumps(cost)[:EXTENSIONS_LOG_CHARS]}" if cost else "")
        return data_of(payload)

    def _execute(self, body: str) -> Any:
        """Send ``body`` and give Fusion's response.

        Fusion's call cannot be ended once made, so it runs on a thread of its own and the wait for it is what a cancel or the timeout
        ends: a request given up on finishes by itself and its answer is dropped.
        """
        self.cancel.check()
        outcome: Dict[str, Any] = {}
        done = threading.Event()

        def send() -> None:
            try:
                import adsk.core   # only inside Fusion
                request = adsk.core.HttpRequest.create(FUSION_GRAPHQL_URL, adsk.core.HttpMethods.PostMethod)
                request.setHeader("Content-type", "application/json; charset=utf-8")
                request.data = body
                outcome["response"] = request.executeSync()
            except BaseException as exc:  # noqa: BLE001 - handed to the thread that waits
                outcome["error"] = exc
            finally:
                done.set()

        threading.Thread(target=send, name="MfgToFm_FusionGraphQl", daemon=True).start()
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        while not done.wait(POLL_SECONDS):
            self.cancel.check()
            if time.monotonic() > deadline:
                raise MfgApiError(f"Manufacturing Data Model did not answer within {REQUEST_TIMEOUT_SECONDS} seconds.", transient=True)
        self.cancel.check()
        error = outcome.get("error")
        if isinstance(error, RuntimeError):
            raise MfgApiError(f"Fusion could not send the request: {error}", transient=True) from error
        if error is not None:
            raise error
        return outcome["response"]

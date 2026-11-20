"""Fusion Manage REST client.

The one place that knows how to address a tenant and make authenticated calls. The feature classes (items, BOMs, files and the
rest) take an ``FmClient`` instead of building URLs and headers themselves.
"""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterator, NamedTuple, Optional, Tuple

from ..auth.auth_service import AuthService
from ..config.hub import tenant_code
from ..config.models import ConnectionSettings
from ..core.cancel import ADDIN, CancelToken
from ..core.http import open_url
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch

log = get_logger("fm.client")


FM_HOST_SUFFIX = ".autodeskplm360.net"
DEBUG_BODY = 20000   # bytes of a request or answer kept in a verbose log
ANSWER_LOG_BYTES = 500   # bytes of a write's answer kept in the normal log
ERROR_BODY_BYTES = 8000   # bytes of a refusal read, for the log and for a form that shows what was refused
ERROR_MESSAGE_CHARS = 300   # characters of it that go into the message the user can see
NOT_JSON_LOG_BYTES = 300   # bytes of an answer that was not JSON kept in the log
EMBEDDED_FILE_LOG_CHARS = 40   # characters of each file embedded in a request kept in the log
REQUEST_TIMEOUT_SECONDS = 15
WRITE_TIMEOUT_SECONDS = 60   # creating an item with an image can take longer than a read
UPLOAD_TIMEOUT_SECONDS = 300   # a STEP of an assembly can be large
UPLOAD_CHUNK_BYTES = 64 * 1024   # a file goes out in pieces this big, so progress can be shown
READ_ATTEMPTS = 3
NO_RESPONSE = 0   # the ``status`` of an error that had no HTTP response
NO_CONTENT = 204   # the status of an answer with nothing in it, e.g. a search with no hits
RETRY_STATUSES = (429, 502, 503, 504, NO_RESPONSE)   # worth another try: a busy or failing gateway, a timeout or a lost connection
RETRY_SECONDS = 2   # wait before the second try, twice that before the third
_ENCODED_SEPARATORS = ("%2e", "%2f", "%5c")   # an encoded dot, slash or backslash
_DATA_URI = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+")   # a file embedded in a request body (an image field)

# Path roots of the REST API, shared by every feature that builds a url.
WORKSPACES = "/api/v3/workspaces"
LOOKUPS = "/api/v3/lookups"
VIEW = "views/1"   # the view whose fields and sections an item is written through


class FmApiError(Exception):
    """Raised when a Fusion Manage request fails or returns bad data."""

    def __init__(self, message: str, status: int = NO_RESPONSE, body: str = "") -> None:
        super().__init__(message)
        self.status = status   # HTTP status, or ``NO_RESPONSE`` when there was none
        self.body = body   # what Fusion Manage said in a refusal, as it said it (the start of it): for a caller that reads it

    @property
    def outcome_unknown(self) -> bool:
        """Whether a write that failed this way may still have been done: it got no answer, or a server or gateway error (500, 502, 504 ...)
        that can come after the server made the change. Any other refusal (400, 403, 404, 409 ...) is definitive: nothing was done."""
        return self.status == NO_RESPONSE or self.status >= 500


def _clip(data: bytes) -> str:
    """The start of a request or answer, for a verbose log."""
    return data[:DEBUG_BODY].decode("utf-8", "replace")


def _readable(payload: Optional[bytes]) -> str:
    """A request body for the log with each embedded file (a ``data:`` uri) cut to its start, so the fields can be read."""
    return _DATA_URI.sub(lambda match: match.group(0)[:EMBEDDED_FILE_LOG_CHARS] + "...", (payload or b"").decode("utf-8", "replace"))


def _said(exc: urllib.error.HTTPError) -> str:
    """What Fusion Manage said in a refusal (the start of it)."""
    return exc.read()[:ERROR_BODY_BYTES].decode("utf-8", "replace")


def _read_failure(exc: OSError, path: str) -> FmApiError:
    """The error for a read of ``path`` that failed: a refusal (``HTTPError``, logged with what Fusion Manage said) or no answer at all."""
    if isinstance(exc, urllib.error.HTTPError):
        log.error("Fusion Manage HTTP %s for %s: %s", exc.code, path, _said(exc))
        return FmApiError(t("data.fm_returned_status", status=exc.code, path=path), exc.code)
    return FmApiError(t("data.fm_request_failed", path=path, reason=exc))


def last_segment(link: Any) -> str:
    """The id at the end of a link such as ``/api/v3/workspaces/242/views/1/fields/TITLE`` ("" if not text)."""
    return link.rstrip("/").rsplit("/", 1)[-1] if isinstance(link, str) else ""


def id_of(node: Dict[str, Any]) -> str:
    """The id of a row: the end of its ``__self__``, ``link`` or ``urn``, else its ``id`` ("" if it has none)."""
    return last_segment(node.get("__self__") or node.get("link") or node.get("urn")) or str(node.get("id") or "")


# What a signed upload address can ask to be sent with the file
SIGNED_HEADER_PREFIXES = ("x-amz-", "x-goog-", "x-ms-", "content-md5", "content-type", "content-encoding", "cache-control")


def signed_headers(extra: Dict[str, str]) -> Dict[str, str]:
    """The headers of ``extra`` that belong with a signed upload; the rest (``Host``, ``Content-Length``, ``Authorization``, ...) are left out."""
    kept = {k: v for k, v in extra.items() if k.lower().startswith(SIGNED_HEADER_PREFIXES)}
    if len(kept) != len(extra):
        log.warning("Left out upload headers not meant for a signed address: %s", sorted(set(extra) - set(kept)))
    return kept


def checked_path(path: str) -> str:
    """``path`` if it stays inside the API: ids reach a path from the page, so one that climbs out of its place (``..``, an encoded
    slash or dot, a backslash) or breaks the request line is refused here, for every request."""
    base = path.split("?", 1)[0]   # the query string may hold what the path may not
    refused = (
        not path.startswith("/")
        or "#" in path or "\\" in path
        or any(ord(c) <= 32 or ord(c) == 127 for c in base)   # a space or a control character breaks the request line
        or ".." in base.split("/")
        or any(code in base.lower() for code in _ENCODED_SEPARATORS))
    if refused:
        raise FmApiError(t("data.fm_bad_address"))
    return path


class SendResult(NamedTuple):
    """What a write returned: HTTP status, response headers and the parsed JSON (None when there was none)."""
    status: int
    headers: Dict[str, str]
    data: Any


def _chunks(content: bytes, progress: Callable[[float], None]) -> Iterator[bytes]:
    """``content`` in pieces; ``progress`` is told the fraction handed over after each."""
    size = max(len(content), 1)
    for start in range(0, len(content), UPLOAD_CHUNK_BYTES):
        yield content[start:start + UPLOAD_CHUNK_BYTES]
        progress(min(1.0, (start + UPLOAD_CHUNK_BYTES) / size))


class FmClient:
    """Authenticated access to one Fusion Manage tenant."""

    def __init__(self, settings: ConnectionSettings, auth: AuthService, cancel: Optional[CancelToken] = None) -> None:
        self._settings = settings
        self._auth = auth
        self.cancel = cancel or ADDIN   # every request checks it, and is ended by it: work for a tab or panel gives its own

    def with_cancel(self, cancel: CancelToken) -> "FmClient":
        """A client for the same tenant and sign-in whose requests are checked and ended by ``cancel`` instead."""
        return FmClient(self._settings, self._auth, cancel)

    @property
    def tenant(self) -> str:
        """The tenant name of the connection settings, without surrounding space (it may be empty: ``base_url`` refuses that)."""
        return self._settings.tenant.strip()

    @property
    def base_url(self) -> str:
        """API root, e.g. https://acme.autodeskplm360.net. The tenant must be a plain host name label, so the access token
        can only go to a ``*.autodeskplm360.net`` host."""
        if not self.tenant or tenant_code(self.tenant) != self.tenant:
            raise FmApiError(t("data.fm_no_hub"))
        return f"https://{self.tenant}{FM_HOST_SUFFIX}"

    def access_token(self) -> str:
        """A valid access token (an expired one is refreshed); raises ``AuthError`` when not signed in."""
        return self._auth.get_access_token(self._settings)

    @staticmethod
    def https_only(url: Any) -> str:
        """Accept only https links so a bad response cannot inject other schemes."""
        return url if isinstance(url, str) and url.lower().startswith("https://") else ""

    def get_json(self, path: str, accept: str = "application/json") -> Any:
        """GET ``path`` (e.g. ``/api/v3/users/@me``) and return parsed JSON.

        Raises ``AuthError`` if there is no valid session and ``FmApiError``
        for network, HTTP or parsing failures. The access token is fetched per
        call so an expired one is refreshed transparently. A read that fails
        in a way that usually passes (a gateway error or a timeout) is tried
        again a few times, since reading changes nothing.
        """
        url = self._url(path)   # an address that is refused, or no usable hub, is not a failure that passes: it is not tried again
        for attempt in range(1, READ_ATTEMPTS + 1):
            try:
                return self._get_once(url, path, accept)
            except FmApiError as exc:
                if attempt == READ_ATTEMPTS or exc.status not in RETRY_STATUSES:
                    raise
                log.warning("Fusion Manage read of %s failed (%s), attempt %d of %d", path, exc, attempt, READ_ATTEMPTS)
                self.cancel.wait(RETRY_SECONDS * attempt)

    def _url(self, path: str) -> str:
        """The address of ``path`` in the tenant; ``FmApiError`` when ``path`` is refused or no usable hub is active."""
        return f"{self.base_url}{checked_path(path)}"

    def _request(self, url: str, accept: str, method: Optional[str] = None, data: Optional[bytes] = None,
                 content_type: str = "") -> urllib.request.Request:
        """A request to ``url`` signed in as the user. The access token is fetched per request, so an expired one is refreshed."""
        headers = {"Accept": accept, "Authorization": f"Bearer {self.access_token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        return urllib.request.Request(url, data=data, headers=headers, method=method)

    def _get_once(self, url: str, path: str, accept: str) -> Any:
        """One GET of ``url``: the parsed JSON, or None when the answer has no content. Raises ``FmApiError`` when it fails or is not JSON."""
        self.cancel.check()
        watch = Stopwatch()
        request = self._request(url, accept)
        token_seconds = watch.lap()
        try:
            with open_url(request, REQUEST_TIMEOUT_SECONDS, self.cancel) as response:
                first_byte_seconds = watch.lap()   # until the response headers arrived
                body = response.read()
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("GET %s -> %s (token %.2fs, first byte %.2fs, download %.2fs, %d bytes): %s", path, response.status,
                              token_seconds, first_byte_seconds, watch.lap(), len(body), _clip(body))
                if response.status == NO_CONTENT or not body.strip():
                    return None
                try:
                    return json.loads(body)
                except ValueError as exc:
                    log.error("Fusion Manage HTTP %s for %s was not JSON (%s): %r", response.status, path,
                              response.headers.get("Content-Type"), body[:NOT_JSON_LOG_BYTES])
                    raise FmApiError(t("data.fm_request_failed", path=path, reason=exc)) from exc
        except OSError as exc:
            raise _read_failure(exc, path) from exc

    def get_bytes(self, path: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Tuple[bytes, str]:
        """GET ``path`` (an image or a file) and return ``(body, content type)``. Raises ``FmApiError`` on failure.

        A file is often served from another host after a redirect; the sign-in is not sent there.
        """
        self.cancel.check()
        request = self._request(self._url(path), "*/*")
        watch = Stopwatch()
        try:
            with open_url(request, timeout, self.cancel) as response:
                body = response.read()
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("GET %s -> %s (%.2fs, %d bytes)", path, response.status, watch.lap(), len(body))
                return body, str(response.headers.get("Content-Type") or "")
        except OSError as exc:
            raise _read_failure(exc, path) from exc

    def put_bytes(self, url: str, content: bytes, headers: Optional[Dict[str, str]] = None, timeout: int = UPLOAD_TIMEOUT_SECONDS,
                  progress: Optional[Callable[[float], None]] = None) -> int:
        """PUT ``content`` to a signed https ``url`` (it carries its own access, so no sign-in is sent); return the status.

        ``progress(fraction)`` is called as the bytes go out (0 to 1). Only the client's own token ends it (the add-in's, unless
        the caller gave one): a file being attached is not stopped by leaving a tab.
        """
        if not self.https_only(url):
            raise FmApiError(t("data.fm_upload_not_https"))
        body: Any = content
        if progress is not None:   # sent in pieces so the caller can see how far it has got
            body = _chunks(content, progress)
        request = urllib.request.Request(url, data=body, method="PUT", headers={
            "Content-Type": "application/octet-stream", "Content-Length": str(len(content)), **signed_headers(headers or {})})
        began = time.monotonic()
        try:
            with open_url(request, timeout, self.cancel) as response:
                log.info("PUT of %d bytes -> %s in %.1fs", len(content), response.status, time.monotonic() - began)
                return response.status
        except urllib.error.HTTPError as exc:
            said = _said(exc)
            log.error("Upload HTTP %s: %s", exc.code, said)
            raise FmApiError(t("data.fm_upload_returned", status=exc.code, said=said[:ERROR_MESSAGE_CHARS]), exc.code) from exc
        except OSError as exc:
            raise FmApiError(t("data.fm_upload_failed", reason=exc)) from exc

    def send_json(self, method: str, path: str, body: Any = None, content_type: str = "application/json") -> SendResult:
        """POST, PATCH or DELETE ``path`` with ``body`` as JSON; return the status, headers and parsed answer.

        ``content_type`` is the type the body is sent as (a view definition goes back as the META type it was read as).
        A write can have no answer (201 with only a ``Location`` header, 204), so ``data`` may be None.
        A refusal raises ``FmApiError`` whose message carries what Fusion Manage said, since that is
        the reason the user needs.
        """
        self.cancel.check()
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = self._request(self._url(path), "application/json", method, payload, content_type if payload is not None else "")
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%s %s body: %s", method, path, _clip(payload or b""))
        began = time.monotonic()
        try:
            with open_url(request, WRITE_TIMEOUT_SECONDS, self.cancel) as response:
                raw = response.read()
                try:
                    data = json.loads(raw) if raw.strip() else None
                except ValueError as exc:
                    log.error("Fusion Manage HTTP %s for %s %s was not JSON: %r", response.status, method, path, raw[:NOT_JSON_LOG_BYTES])
                    raise FmApiError(t("data.fm_request_failed_method", method=method, path=path, reason=exc), response.status) from exc
                result = SendResult(response.status, dict(response.headers.items()), data)
                log.info("Fusion Manage %s %s -> %s %s", method, path, result.status, raw[:ANSWER_LOG_BYTES].decode("utf-8", "replace"))
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("%s %s took %.2fs, answered: %s", method, path, time.monotonic() - began, _clip(raw))
                return result
        except urllib.error.HTTPError as exc:
            said = _said(exc)
            log.error("Fusion Manage HTTP %s for %s %s: %s; it sent: %s", exc.code, method, path, said, _readable(payload))
            raise FmApiError(t("data.fm_returned_status_said", status=exc.code, method=method, path=path, said=said[:ERROR_MESSAGE_CHARS]), exc.code, said) from exc
        except OSError as exc:
            raise FmApiError(t("data.fm_request_failed_method", method=method, path=path, reason=exc)) from exc

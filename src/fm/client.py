"""Fusion Manage REST client.

The one place that knows how to address a tenant and make authenticated calls. The feature classes (items, BOMs, files and the
rest) take an ``FmClient`` instead of building URLs and headers themselves.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterator, NamedTuple, Optional, Tuple

from ..auth.auth_service import AuthService
from ..config.hub import tenant_code
from ..config.models import ConnectionSettings
from ..core.cancel import ADDIN, CancelToken
from ..core.http import open_url
from ..core.logging_setup import get_logger
from ..core.timing import Stopwatch

log = get_logger("fm.client")


FM_HOST_SUFFIX = ".autodeskplm360.net"
DEBUG_BODY = 20000   # bytes of a request or answer kept in a verbose log
ANSWER_LOG_BYTES = 500   # bytes of a write's answer kept in the normal log
ERROR_BODY_BYTES = 1000   # bytes of a refusal read, for the log
ERROR_MESSAGE_CHARS = 300   # characters of it that go into the message the user can see
REQUEST_TIMEOUT_SECONDS = 15
WRITE_TIMEOUT_SECONDS = 60   # creating an item with an image can take longer than a read
UPLOAD_TIMEOUT_SECONDS = 300   # a STEP of an assembly can be large
UPLOAD_CHUNK_BYTES = 64 * 1024   # a file goes out in pieces this big, so progress can be shown
READ_ATTEMPTS = 3
NO_RESPONSE = 0   # the ``status`` of an error that had no HTTP response
RETRY_STATUSES = (429, 502, 503, 504, NO_RESPONSE)   # worth another try: a busy or failing gateway, a timeout or a lost connection
RETRY_SECONDS = 2   # wait before the second try, twice that before the third

# Path roots of the REST API, shared by every feature that builds a url.
WORKSPACES = "/api/v3/workspaces"
LOOKUPS = "/api/v3/lookups"


class FmApiError(Exception):
    """Raised when a Fusion Manage request fails or returns bad data."""

    def __init__(self, message: str, status: int = NO_RESPONSE) -> None:
        super().__init__(message)
        self.status = status   # HTTP status, or ``NO_RESPONSE`` when there was none


def _clip(data: bytes) -> str:
    """The start of a request or answer, for a verbose log."""
    return data[:DEBUG_BODY].decode("utf-8", "replace")


def _said(exc: urllib.error.HTTPError) -> str:
    """What Fusion Manage said in a refusal (the start of it)."""
    return exc.read()[:ERROR_BODY_BYTES].decode("utf-8", "replace")


def last_segment(link: Any) -> str:
    """The id at the end of a link such as ``/api/v3/workspaces/242/views/1/fields/TITLE`` ("" if not text)."""
    return link.rstrip("/").rsplit("/", 1)[-1] if isinstance(link, str) else ""


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
    base = path.split("?", 1)[0]
    if (not path.startswith("/") or "#" in path or "\\" in path or any(ord(c) <= 32 or ord(c) == 127 for c in base)
            or ".." in base.split("/") or any(code in base.lower() for code in ("%2e", "%2f", "%5c"))):
        raise FmApiError("That address is not one Fusion Manage can be asked for.")
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

    @property
    def tenant(self) -> str:
        return self._settings.tenant.strip()

    @property
    def base_url(self) -> str:
        """API root, e.g. https://acme.autodeskplm360.net. The tenant must be a plain host name label, so the access token
        can only go to a ``*.autodeskplm360.net`` host."""
        if not self.tenant or tenant_code(self.tenant) != self.tenant:
            raise FmApiError("No usable Fusion hub is active; open the hub of your Fusion Manage tenant.")
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
                if response.status == 204 or not body.strip():   # no content, e.g. a search with no hits
                    return None
                try:
                    return json.loads(body)
                except ValueError:
                    log.error("Fusion Manage HTTP %s for %s was not JSON (%s): %r", response.status, path,
                              response.headers.get("Content-Type"), body[:300])
                    raise
        except urllib.error.HTTPError as exc:
            log.error("Fusion Manage HTTP %s for %s: %s", exc.code, path, _said(exc))
            raise FmApiError(f"Fusion Manage returned {exc.code} for {path}", exc.code) from exc
        except (OSError, ValueError) as exc:
            raise FmApiError(f"Fusion Manage request failed for {path}: {exc}") from exc

    def get_bytes(self, path: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Tuple[bytes, str]:
        """GET ``path`` (an image or a file) and return ``(body, content type)``. Raises ``FmApiError`` on failure.

        A file is often served from another host after a redirect; the sign-in is not sent there.
        """
        self.cancel.check()
        request = self._request(self._url(path), "*/*")
        try:
            with open_url(request, timeout, self.cancel) as response:
                return response.read(), str(response.headers.get("Content-Type") or "")
        except urllib.error.HTTPError as exc:
            raise FmApiError(f"Fusion Manage returned {exc.code} for {path}", exc.code) from exc
        except OSError as exc:
            raise FmApiError(f"Fusion Manage request failed for {path}: {exc}") from exc

    def put_bytes(self, url: str, content: bytes, headers: Optional[Dict[str, str]] = None, timeout: int = UPLOAD_TIMEOUT_SECONDS,
                  progress: Optional[Callable[[float], None]] = None) -> int:
        """PUT ``content`` to a signed https ``url`` (it carries its own access, so no sign-in is sent); return the status.

        ``progress(fraction)`` is called as the bytes go out (0 to 1). Only the client's own token ends it (the add-in's, unless
        the caller gave one): a file being attached is not stopped by leaving a tab.
        """
        if not self.https_only(url):
            raise FmApiError("The upload address Fusion Manage gave is not https.")
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
            raise FmApiError(f"The upload returned {exc.code}: {said[:ERROR_MESSAGE_CHARS]}", exc.code) from exc
        except OSError as exc:
            raise FmApiError(f"The upload failed: {exc}") from exc

    def send_json(self, method: str, path: str, body: Any = None) -> SendResult:
        """POST, PATCH or DELETE ``path`` with ``body`` as JSON; return the status, headers and parsed answer.

        A write can have no answer (201 with only a ``Location`` header, 204), so ``data`` may be None.
        A refusal raises ``FmApiError`` whose message carries what Fusion Manage said, since that is
        the reason the user needs.
        """
        self.cancel.check()
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = self._request(self._url(path), "application/json", method, payload, "application/json" if payload is not None else "")
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%s %s body: %s", method, path, _clip(payload or b""))
        began = time.monotonic()
        try:
            with open_url(request, WRITE_TIMEOUT_SECONDS, self.cancel) as response:
                raw = response.read()
                try:
                    data = json.loads(raw) if raw.strip() else None
                except ValueError:
                    log.warning("The answer to %s %s was not JSON; it is read as no answer", method, path)
                    data = None
                result = SendResult(response.status, dict(response.headers.items()), data)
                log.info("Fusion Manage %s %s -> %s %s", method, path, result.status, raw[:ANSWER_LOG_BYTES].decode("utf-8", "replace"))
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("%s %s took %.2fs, answered: %s", method, path, time.monotonic() - began, _clip(raw))
                return result
        except urllib.error.HTTPError as exc:
            said = _said(exc)
            log.error("Fusion Manage HTTP %s for %s %s: %s", exc.code, method, path, said)
            raise FmApiError(f"Fusion Manage returned {exc.code} for {method} {path}: {said[:ERROR_MESSAGE_CHARS]}", exc.code) from exc
        except OSError as exc:
            raise FmApiError(f"Fusion Manage request failed for {method} {path}: {exc}") from exc

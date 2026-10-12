"""Fusion Manage REST client.

Single place that knows how to address a tenant and make authenticated calls.
Feature classes (profile today; items, BOMs and files later) take an
``FmClient`` instead of building URLs and headers themselves.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterator, NamedTuple, Optional, Tuple

from ..auth.auth_service import AuthService
from ..config.models import ConnectionSettings
from ..core.logging_setup import get_logger

log = get_logger("fm.client")


def _clip(data: bytes) -> str:
    """The start of a request or answer, for a verbose log."""
    return data[:DEBUG_BODY].decode("utf-8", "replace")

FM_HOST_SUFFIX =".autodeskplm360.net"
DEBUG_BODY = 20000   # characters of a request or answer kept in a verbose log
REQUEST_TIMEOUT_SECONDS = 15
WRITE_TIMEOUT_SECONDS = 60   # creating an item with an image can take longer than a read
UPLOAD_TIMEOUT_SECONDS = 300   # a STEP of an assembly can be large
UPLOAD_CHUNK_BYTES = 64 * 1024   # a file goes out in pieces this big, so progress can be shown
READ_ATTEMPTS = 3
RETRY_STATUSES = (429, 502, 503, 504)   # worth another try; a timeout or lost connection (status 0) is too
RETRY_SECONDS = 2   # wait before the second try, twice that before the third

# Path roots of the REST API, shared by every feature that builds a url.
WORKSPACES = "/api/v3/workspaces"
LOOKUPS = "/api/v3/lookups"


def last_segment(link: Any) -> str:
    """The id at the end of a link such as ``/api/v3/workspaces/242/views/1/fields/TITLE`` ("" if not text)."""
    return link.rstrip("/").rsplit("/", 1)[-1] if isinstance(link, str) else ""


class _KeepSignInHere(urllib.request.HTTPRedirectHandler):
    """Follows a redirect, but sends the access token only to the host it was meant for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_KeepSignInHere)


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
        call so an expired one is refreshed transparently. A read that fails
        in a way that usually passes (a gateway error or a timeout) is tried
        again a few times, since reading changes nothing.
        """
        for attempt in range(1, READ_ATTEMPTS + 1):
            try:
                return self._get_once(path, accept)
            except FmApiError as exc:
                if attempt == READ_ATTEMPTS or not (exc.status in RETRY_STATUSES or exc.status == 0):
                    raise
                log.warning("Fusion Manage read of %s failed (%s), attempt %d of %d", path, exc, attempt, READ_ATTEMPTS)
                time.sleep(RETRY_SECONDS * attempt)

    def _get_once(self, path: str, accept: str) -> Any:
        asked = time.monotonic()
        token = self._auth.get_access_token(self._settings)
        token_seconds = time.monotonic() - asked
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Accept": accept, "Authorization": f"Bearer {token}"},
        )
        began = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                waited = time.monotonic() - began   # until the response headers arrived
                body = response.read()
                log.info("TIMING fm GET %s: token %.2fs, first byte %.2fs, download %.2fs, %d bytes",
                         path.split("?")[0], token_seconds, waited, time.monotonic() - began - waited, len(body))
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("GET %s -> %s in %.2fs: %s", path, response.status, time.monotonic() - began, _clip(body))
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

    def get_bytes(self, path: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Tuple[bytes, str]:
        """GET ``path`` (an image or a file) and return ``(body, content type)``. Raises ``FmApiError`` on failure.

        A file is often served from another host after a redirect; the sign-in is not sent there.
        """
        token = self._auth.get_access_token(self._settings)
        request = urllib.request.Request(f"{self.base_url}{path}", headers={"Accept": "*/*", "Authorization": f"Bearer {token}"})
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                return response.read(), str(response.headers.get("Content-Type") or "")
        except urllib.error.HTTPError as exc:
            raise FmApiError(f"Fusion Manage returned {exc.code} for {path}", exc.code) from exc
        except OSError as exc:
            raise FmApiError(f"Fusion Manage request failed for {path}: {exc}") from exc

    @staticmethod
    def put_bytes(url: str, content: bytes, headers: Optional[Dict[str, str]] = None, timeout: int = UPLOAD_TIMEOUT_SECONDS,
                  progress: Optional[Callable[[float], None]] = None) -> int:
        """PUT ``content`` to a signed https ``url`` (it carries its own access, so no sign-in is sent); return the status.

        ``progress(fraction)`` is called as the bytes go out (0 to 1).
        """
        if not url.lower().startswith("https://"):
            raise FmApiError("The upload address Fusion Manage gave is not https.")
        body: Any = content
        if progress is not None:   # sent in pieces so the caller can see how far it has got
            body = _chunks(content, progress)
        request = urllib.request.Request(url, data=body, method="PUT", headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(content)), **(headers or {})})
        began = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                log.info("PUT of %d bytes -> %s in %.1fs", len(content), response.status, time.monotonic() - began)
                return response.status
        except urllib.error.HTTPError as exc:
            said = exc.read()[:1000].decode("utf-8", "replace")
            log.error("Upload HTTP %s: %s", exc.code, said)
            raise FmApiError(f"The upload returned {exc.code}: {said[:300]}", exc.code) from exc
        except OSError as exc:
            raise FmApiError(f"The upload failed: {exc}") from exc

    def send_json(self, method: str, path: str, body: Any = None) -> SendResult:
        """POST, PATCH or DELETE ``path`` with ``body`` as JSON; return the status, headers and parsed answer.

        A write can have no answer (201 with only a ``Location`` header, 204), so ``data`` may be None.
        A refusal raises ``FmApiError`` whose message carries what Fusion Manage said, since that is
        the reason the user needs.
        """
        token = self._auth.get_access_token(self._settings)
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base_url}{path}", data=payload, headers=headers, method=method)
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%s %s body: %s", method, path, _clip(payload or b""))
        began = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=WRITE_TIMEOUT_SECONDS) as response:
                raw = response.read()
                try:
                    data = json.loads(raw) if raw.strip() else None
                except ValueError:
                    data = None
                result = SendResult(response.status, dict(response.headers.items()), data)
                log.info("Fusion Manage %s %s -> %s %s", method, path, result.status, raw[:500].decode("utf-8", "replace"))
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("%s %s took %.2fs, answered: %s", method, path, time.monotonic() - began, _clip(raw))
                return result
        except urllib.error.HTTPError as exc:
            said = exc.read()[:1000].decode("utf-8", "replace")
            log.error("Fusion Manage HTTP %s for %s %s: %s", exc.code, method, path, said)
            raise FmApiError(f"Fusion Manage returned {exc.code} for {method} {path}: {said[:300]}", exc.code) from exc
        except OSError as exc:
            raise FmApiError(f"Fusion Manage request failed for {method} {path}: {exc}") from exc

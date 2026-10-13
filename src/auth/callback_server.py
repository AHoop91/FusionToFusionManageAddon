"""Loopback HTTP server that captures the OAuth redirect.

After the user signs in, the browser is redirected to
``http://localhost:<port>/callback``. This short-lived server, bound to the
loopback interface only, receives that one request, validates the ``state``
value (CSRF protection) and hands the authorization code back to the caller.
"""

import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from .errors import AuthError

CALLBACK_PATH = "/callback"

_PAGE_STYLE = b"font-family:Segoe UI,sans-serif;text-align:center;margin-top:80px"
_SUCCESS_PAGE = (
    b"<html><body style='" + _PAGE_STYLE + b"'>"
    b"<h2>Signed in</h2><p>You can close this tab and return to Fusion.</p></body></html>"
)
_FAILURE_PAGE = (
    b"<html><body style='" + _PAGE_STYLE + b"'>"
    b"<h2>Sign-in failed</h2><p>Return to Fusion for details.</p></body></html>"
)


class CallbackServer:
    """Serves one redirect on localhost and captures the authorization code."""

    def __init__(self, port: int, expected_state: str) -> None:
        # ``result`` is filled by the request handler: either a code or an error.
        self.result: Dict[str, Optional[str]] = {"code": None, "error": None}
        self._done = threading.Event()
        handler = self._build_handler(self.result, self._done, expected_state)
        try:
            self._server = HTTPServer(("127.0.0.1", port), handler)
        except OSError as exc:
            raise AuthError(f"Callback port {port} is unavailable: {exc}") from exc
        # Short timeout so ``wait`` can notice cancel/timeout between requests.
        self._server.timeout = 0.5

    @staticmethod
    def _build_handler(result: Dict[str, Optional[str]], done: threading.Event, state: str):
        """Create a request handler class bound to this server's state."""

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib naming
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != CALLBACK_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return

                params = urllib.parse.parse_qs(parsed.query)
                if not secrets.compare_digest(params.get("state", [""])[0].encode(), state.encode()):
                    # Not our redirect (another program or a web page): ignore it and keep waiting, so it cannot cancel the sign-in.
                    self.send_response(400)
                    self.end_headers()
                    return
                if "error" in params:
                    result["error"] = params.get("error_description", params["error"])[0]
                else:
                    result["code"] = params.get("code", [""])[0] or None
                    if not result["code"]:
                        result["error"] = "No authorization code returned."

                self.send_response(200 if result["code"] else 400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(_SUCCESS_PAGE if result["code"] else _FAILURE_PAGE)
                done.set()

            def log_message(self, *args: Any) -> None:  # silence stdlib logging
                pass

        return _Handler

    def wait(self, timeout_seconds: int, cancelled: threading.Event) -> Dict[str, Optional[str]]:
        """Block until a redirect arrives, the timeout elapses, or cancel is set."""
        deadline = time.time() + timeout_seconds
        try:
            while not self._done.is_set() and not cancelled.is_set() and time.time() < deadline:
                self._server.handle_request()
        finally:
            self._server.server_close()
        if not self.result["code"] and not self.result["error"]:
            self.result["error"] = "Sign-in cancelled." if cancelled.is_set() else "Sign-in timed out."
        return self.result

"""Loopback HTTP server that captures the OAuth redirect.

After the user signs in, the browser is redirected to
``http://localhost:<port>/callback``. This short-lived server, bound to the
loopback interface only, receives that one request, validates the ``state``
value (CSRF protection) and hands the authorization code back to the caller.
"""

import html
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from .errors import AuthError

CALLBACK_PATH = "/callback"

_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>
body {{ margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: #f3f5f7; font-family: "Segoe UI", system-ui, sans-serif; color: #1f2933; }}
.card {{ box-sizing: border-box; width: min(420px, 90vw); padding: 36px 32px; text-align: center;
  background: #fff; border: 1px solid #dde2e7; border-radius: 10px; box-shadow: 0 4px 16px rgba(0, 0, 0, .08); }}
.icon {{ width: 56px; height: 56px; margin: 0 auto 16px; border-radius: 50%; color: #fff; font-size: 30px;
  line-height: 56px; background: {colour}; }}
h1 {{ margin: 0 0 8px; font-size: 22px; }}
p {{ margin: 0 0 8px; color: #52606d; line-height: 1.5; }}
.detail {{ margin-top: 12px; padding: 10px 12px; text-align: left; font-size: 13px; color: #8f1d1d;
  background: #fdecea; border: 1px solid #f1aeb5; border-radius: 6px; overflow-wrap: anywhere; }}
button {{ margin-top: 18px; padding: 9px 22px; font: inherit; color: #fff; background: #0696d7; border: 0;
  border-radius: 6px; cursor: pointer; }}
button:hover {{ background: #0579b0; }}
</style></head><body><div class="card">
<div class="icon">{icon}</div><h1>{title}</h1><p>{text}</p>{detail}
<button type="button" onclick="window.close()">Close this tab</button>
</div><script>{script}</script></body></html>"""


def _page(ok: bool, error: str = "") -> bytes:
    """The page the browser shows after the redirect. ``error`` is shown as the reason sign-in failed."""
    if ok:
        title, icon, colour = "Authorization received", "&#10003;", "#2e7d32"
        text = "Return to Fusion to finish signing in. You can close this tab."
        detail = ""
        script = ""
    else:
        title, icon, colour = "Sign-in failed", "!", "#c62828"
        text = "Return to Fusion and try again."
        detail = '<div class="detail">' + html.escape(error) + "</div>" if error else ""
        script = ""
    return _PAGE.format(title=title, icon=icon, colour=colour, text=text, detail=detail, script=script).encode("utf-8")


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
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_page(bool(result["code"]), result["error"] or ""))
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

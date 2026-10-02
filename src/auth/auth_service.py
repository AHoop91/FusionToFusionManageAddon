"""High-level sign-in state machine used by the UI.

Login runs on a background thread so Fusion's UI never blocks; the panel polls
``status()``. Only one sign-in can run at a time.
"""

import threading
import time
import webbrowser
from typing import Any, Dict, Optional

from ..config.models import ConnectionSettings
from ..core.logging_setup import get_logger
from .callback_server import CallbackServer
from .errors import AuthError
from .oauth_pkce import (
    build_authorize_url,
    exchange_code,
    generate_pkce,
    refresh_tokens,
)
from .token_store import TokenStore

log = get_logger("auth")

LOGIN_TIMEOUT_SECONDS = 180
# Refresh slightly early so a token never expires mid-request.
EXPIRY_MARGIN_SECONDS = 60

# Sign-in states reported to the panel.
STATE_SIGNED_OUT = "signed_out"
STATE_SIGNING_IN = "signing_in"
STATE_SIGNED_IN = "signed_in"
STATE_ERROR = "error"


class AuthService:
    """Owns tokens for the active connection settings."""

    def __init__(self, store: Optional[TokenStore] = None) -> None:
        self._store = store or TokenStore()
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()   # one refresh at a time: refresh tokens rotate, a second use of the old one fails
        self._state = STATE_SIGNED_OUT
        self._error = ""
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- State -------------------------------------------------------------

    def status(self, settings: ConnectionSettings) -> Dict[str, Any]:
        """Current state; restores a saved session on first call."""
        with self._lock:
            if self._state == STATE_SIGNED_OUT and settings.client_id \
                    and self._store.load(settings.client_id):
                self._state = STATE_SIGNED_IN
            return {"state": self._state, "error": self._error}

    # ---- Sign-in flow ------------------------------------------------------

    def start_login(self, settings: ConnectionSettings) -> None:
        """Begin browser sign-in. Raises AuthError if settings are invalid."""
        problems = settings.validate()
        if problems:
            raise AuthError(" ".join(problems))
        with self._lock:
            if self._state == STATE_SIGNING_IN:
                raise AuthError("Sign-in already in progress.")
            self._state, self._error = STATE_SIGNING_IN, ""
            self._cancel.clear()
        pkce = generate_pkce()
        try:
            server = CallbackServer(settings.callback_port, pkce["state"])
        except AuthError as exc:
            self._fail(str(exc))
            raise
        url = build_authorize_url(settings.client_id, settings.callback_url,
                                  settings.scopes, pkce["challenge"], pkce["state"])
        self._thread = threading.Thread(
            target=self._run_login, args=(settings, pkce["verifier"], server),
            name="MfgToFm-login", daemon=True,
        )
        self._thread.start()
        webbrowser.open(url)

    def _run_login(self, settings: ConnectionSettings, verifier: str, server: CallbackServer) -> None:
        """Background thread: wait for the redirect, then swap the code for tokens."""
        try:
            result = server.wait(LOGIN_TIMEOUT_SECONDS, self._cancel)
            if not result["code"]:
                raise AuthError(result["error"] or "Sign-in failed.")
            tokens = exchange_code(settings.client_id, result["code"],
                                   settings.callback_url, verifier)
            self._store.save(settings.client_id, tokens)
            with self._lock:
                self._state = STATE_SIGNED_IN
            log.info("Signed in")
        except AuthError as exc:
            self._fail(str(exc))
        except Exception as exc:  # noqa: BLE001 - background thread must not die silently
            log.exception("Unexpected sign-in failure")
            self._fail(f"Unexpected error: {exc}")

    def _fail(self, message: str) -> None:
        with self._lock:
            self._state, self._error = STATE_ERROR, message
        log.warning("Sign-in failed: %s", message)

    def cancel_login(self) -> None:
        """Abort a pending browser sign-in."""
        self._cancel.set()

    def sign_out(self, settings: ConnectionSettings) -> None:
        """Forget the stored session for this client id."""
        if settings.client_id:
            self._store.clear(settings.client_id)
        with self._lock:
            self._state, self._error = STATE_SIGNED_OUT, ""

    # ---- Token access ------------------------------------------------------

    def get_access_token(self, settings: ConnectionSettings) -> str:
        """Return a valid access token, refreshing if near expiry.

        Calls from several threads wait while one of them refreshes, then use its new token.
        """
        tokens = self._store.load(settings.client_id)
        if not tokens:
            raise AuthError("Not signed in.")
        if self._fresh(tokens):
            return tokens["access_token"]
        with self._refresh_lock:
            tokens = self._store.load(settings.client_id)   # another thread may have refreshed while this one waited
            if not tokens:
                raise AuthError("Not signed in.")
            if self._fresh(tokens):
                return tokens["access_token"]
            refresh = tokens.get("refresh_token")
            if not refresh:
                raise AuthError("Session expired; sign in again.")
            try:
                fresh = refresh_tokens(settings.client_id, refresh, settings.scopes)
            except AuthError:
                self.sign_out(settings)
                raise
            # Refresh tokens rotate; keep the old one if none is returned.
            fresh.setdefault("refresh_token", refresh)
            self._store.save(settings.client_id, fresh)
            return fresh["access_token"]

    @staticmethod
    def _fresh(tokens: Dict[str, Any]) -> bool:
        return tokens.get("expires_at", 0) - EXPIRY_MARGIN_SECONDS > time.time()

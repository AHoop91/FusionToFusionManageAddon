"""High-level sign-in state machine used by the UI.

Login runs on a background thread so Fusion's UI never blocks; the panel polls
``status()``. Only one sign-in can run at a time.

Each Client ID has a session generation, which a sign-out and a new sign-in raise. A sign-in or a token refresh notes it when it starts and may save its
tokens (or change the state) only while it is still the one it noted, so one that was under way when the user signed out cannot bring
the session back.
"""

import threading
import time
import webbrowser
from typing import Any, Callable, Dict, Optional

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
        self._client_id = ""   # the Client ID the last sign-in was started for
        self._generations: Dict[str, int] = {}   # client id -> session generation, raised by a sign-out (read and changed with ``_lock`` held)
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_login_done: Optional[Callable[[], None]] = None

    def set_on_login_done(self, callback: Optional[Callable[[], None]]) -> None:
        """Call ``callback`` (on the sign-in's thread) when a sign-in ends, however it ends, so the panel need not ask how it went."""
        self._on_login_done = callback

    # ---- State -------------------------------------------------------------

    def status(self, settings: ConnectionSettings) -> Dict[str, Any]:
        """Current state for ``settings``; restores a saved session on first call. Settings differ from hub to hub, so being signed in
        means a session is kept for this Client ID: another hub's sign-in is not this one's."""
        with self._lock:
            if self._state == STATE_ERROR and settings.client_id != self._client_id:
                self._state, self._error = STATE_SIGNED_OUT, ""   # the failure was of another connection
            if self._state in (STATE_SIGNED_OUT, STATE_SIGNED_IN):
                has_session = bool(settings.client_id and self._store.load(settings.client_id))
                self._state = STATE_SIGNED_IN if has_session else STATE_SIGNED_OUT
            return {"state": self._state, "error": self._error}

    # ---- Sign-in flow ------------------------------------------------------

    def start_login(self, settings: ConnectionSettings) -> None:
        """Begin browser sign-in. Raises AuthError if settings are invalid."""
        problems = settings.validate(require_tenant=False)   # signing in does not need the tenant
        if problems:
            raise AuthError(" ".join(problems))
        with self._lock:
            if self._state == STATE_SIGNING_IN:
                raise AuthError("Sign-in already in progress.")
            self._state, self._error, self._client_id = STATE_SIGNING_IN, "", settings.client_id
            generation = self._generations.get(settings.client_id, 0)
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
            target=self._run_login, args=(settings, pkce["verifier"], server, generation),
            name="MfgToFm-login", daemon=True,
        )
        self._thread.start()
        webbrowser.open(url)

    def _run_login(self, settings: ConnectionSettings, verifier: str, server: CallbackServer, generation: int) -> None:
        """Background thread: wait for the redirect, then swap the code for tokens. ``generation`` is the session's when the sign-in began:
        a sign-out since then ends it without a trace (no tokens kept, no state changed)."""
        try:
            result = server.wait(LOGIN_TIMEOUT_SECONDS, self._cancel)
            if not result["code"]:
                raise AuthError(result["error"] or "Sign-in failed.")
            tokens = exchange_code(settings.client_id, result["code"],
                                   settings.callback_url, verifier)
            with self._lock:   # the check and the save are one step: a sign-out cannot come between them
                if self._generations.get(settings.client_id, 0) != generation:
                    log.info("Sign-in dropped: the user signed out while it was under way")
                    return
                self._store.save(settings.client_id, tokens)
                self._generations[settings.client_id] = generation + 1   # a new session: a refresh of the one before it cannot save over it
                self._state = STATE_SIGNED_IN
            log.info("Signed in")
        except AuthError as exc:
            self._fail(str(exc), settings.client_id, generation)
        except Exception as exc:  # noqa: BLE001 - background thread must not die silently
            log.exception("Unexpected sign-in failure")
            self._fail(f"Unexpected error: {exc}", settings.client_id, generation)
        finally:
            callback = self._on_login_done
            if callback is not None:
                try:
                    callback()
                except Exception:  # noqa: BLE001 - telling the panel is a courtesy
                    log.exception("Could not report the end of the sign-in")

    def _fail(self, message: str, client_id: str = "", generation: Optional[int] = None) -> None:
        """Report a failed sign-in, unless the user signed out since it began (``generation``): it is over, not failed."""
        with self._lock:
            if generation is not None and self._generations.get(client_id, 0) != generation:
                log.info("Sign-in ended after a sign-out: %s", message)
                return
            self._state, self._error = STATE_ERROR, message
        log.warning("Sign-in failed: %s", message)

    def cancel_login(self) -> None:
        """Abort a pending browser sign-in."""
        self._cancel.set()

    def sign_out(self, settings: ConnectionSettings, generation: Optional[int] = None) -> bool:
        """Forget the stored session for this client id, and end every sign-in and refresh under way for it (they would save tokens again).
        With ``generation``, only when the session is still that one (False when it is not): a refresh the server refused must not sign
        out a session that began after it did. True when it signed out."""
        client_id = settings.client_id
        with self._lock:
            if generation is not None and self._generations.get(client_id, 0) != generation:
                return False
            self._generations[client_id] = self._generations.get(client_id, 0) + 1
            if client_id:
                self._store.clear(client_id)
            if self._state == STATE_SIGNING_IN and self._client_id == client_id:
                self._cancel.set()   # the browser wait ends, and frees the callback port
            self._state, self._error = STATE_SIGNED_OUT, ""
        return True

    # ---- Token access ------------------------------------------------------

    def get_access_token(self, settings: ConnectionSettings) -> str:
        """Return a valid access token, refreshing if near expiry.

        Calls from several threads wait while one of them refreshes, then use its new token.
        """
        with self._lock:
            generation = self._generations.get(settings.client_id, 0)   # the session this call belongs to
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
            except AuthError as exc:
                if exc.rejected:   # the refresh token is dead; a network or server failure keeps the session for the next try
                    self.sign_out(settings, generation)
                raise
            # Refresh tokens rotate; keep the old one if none is returned.
            fresh.setdefault("refresh_token", refresh)
            with self._lock:   # the check and the save are one step: a sign-out during the refresh must not be undone by it
                if self._generations.get(settings.client_id, 0) != generation:
                    raise AuthError("Not signed in.")
                self._store.save(settings.client_id, fresh)
            return fresh["access_token"]

    @staticmethod
    def _fresh(tokens: Dict[str, Any]) -> bool:
        return tokens.get("expires_at", 0) - EXPIRY_MARGIN_SECONDS > time.time()

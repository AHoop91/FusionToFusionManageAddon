"""Palette actions for sign-in state, login, logout and the user profile."""

import threading
from typing import Any, Dict, Set, Tuple

from ...auth.auth_service import STATE_ERROR, STATE_SIGNED_OUT, STATE_SIGNING_IN, AuthService
from ...config.config_service import CompanyModeUnavailable, ConfigService
from ...fm.client import FmClient
from ...fm.profile import ProfileService
from ...fm.ttl_cache import TtlCache
from ..message_bridge import MessageBridge
from .background import Runner, in_thread

PROFILE_SECONDS = 600
PROFILE_ACTION = "auth_profile"

Key = Tuple[str, str]   # (tenant, client id): the sign-in settings a profile was read under


class ProfileReads:
    """The signed-in user's profile, read in the background.

    A read is a network call with retries that wait, so it never runs on Fusion's thread: ``get`` answers ``{"pending": True}`` and
    pushes the profile to the panels when the read is done. The user's name and picture seldom change and a panel opens often, so a
    profile is kept for a while. Any thread may use it.
    """

    def __init__(self, bridge: MessageBridge, config: ConfigService, auth: AuthService, seconds: float = PROFILE_SECONDS,
                 run: Runner = in_thread) -> None:
        self._bridge, self._config, self._auth, self._run = bridge, config, auth, run
        self._kept = TtlCache(seconds)
        self._done: Dict[Key, Dict[str, Any]] = {}   # a read that has finished and has not been handed to a panel yet
        self._running: Set[Key] = set()
        self._generation = 0   # counts the sign-outs: a read that began before one is of the user who left
        self._lock = threading.Lock()

    def get(self) -> Dict[str, Any]:
        """The profile, or ``{"pending": True}`` while it is read."""
        settings = self._config.effective_settings()
        key = (settings.tenant, settings.client_id)
        profile = self._kept.get(key)
        if profile is not None:
            return profile
        with self._lock:
            if key in self._done:
                return self._done.pop(key)
            if key in self._running:
                return {"pending": True}
            self._running.add(key)
            generation = self._generation
        client = FmClient(settings, self._auth)
        self._run(lambda: self._read(key, client, generation))   # outside the lock: a runner may do the work at once, and the read takes the lock
        return {"pending": True}

    def forget(self) -> None:
        """Drop every profile and abandon the reads under way: what they find is not the next user's."""
        with self._lock:
            self._generation += 1
            self._kept.clear()
            self._done.clear()
            self._running.clear()

    def _read(self, key: Key, client: FmClient, generation: int) -> None:
        service = ProfileService(client)
        try:
            profile = service.current()
        except Exception:  # noqa: BLE001 - never leave the panel waiting
            profile = service.empty()
        with self._lock:
            if generation != self._generation:
                return
            if profile["user_id"] or profile["name"]:   # an answer, not the empty one a failed read gives
                self._kept.put(key, profile)
            self._done[key] = profile
            self._running.discard(key)
        try:
            current = self._config.effective_settings()
        except CompanyModeUnavailable:
            return
        if (current.tenant, current.client_id) == key:   # not if the sign-in settings changed while it was read
            self._bridge.push(PROFILE_ACTION, profile)


def register_auth_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the ``auth_*`` actions."""
    profiles = ProfileReads(bridge, config, auth)

    def auth_status(_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return auth.status(config.effective_settings())
        except CompanyModeUnavailable as exc:
            return {"state": STATE_ERROR, "error": str(exc)}

    def auth_login(_payload: Dict[str, Any]) -> Dict[str, Any]:
        auth.start_login(config.effective_settings())
        return {"state": STATE_SIGNING_IN, "error": ""}

    def auth_cancel(_payload: Dict[str, Any]) -> None:
        auth.cancel_login()

    def auth_logout(_payload: Dict[str, Any]) -> Dict[str, Any]:
        profiles.forget()
        auth.sign_out(config.effective_settings())
        return {"state": STATE_SIGNED_OUT, "error": ""}

    # A browser sign-in ends on its own thread: the panel is told how it went, and does not poll while it waits.
    auth.set_on_login_done(lambda: bridge.push("auth_status", auth_status({})))

    bridge.register("auth_status", auth_status)
    bridge.register("auth_login", auth_login)
    bridge.register("auth_cancel", auth_cancel)
    bridge.register("auth_logout", auth_logout)
    bridge.register(PROFILE_ACTION, lambda _payload: profiles.get())

"""Palette actions for sign-in state, login, logout and the user profile."""

import threading
from typing import Any, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import CompanyModeUnavailable, ConfigService
from ...fm.client import FmClient
from ...fm.profile import ProfileService
from ...fm.ttl_cache import TtlCache
from ..message_bridge import MessageBridge


PROFILE_SECONDS = 600


def register_auth_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the ``auth_*`` actions."""
    profiles = TtlCache(PROFILE_SECONDS)   # the user's name and picture seldom change, and a panel opens often: read them once in a while

    def auth_status(_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return auth.status(config.effective_settings())
        except CompanyModeUnavailable as exc:
            return {"state": "error", "error": str(exc)}

    def auth_login(_payload: Dict[str, Any]) -> Dict[str, Any]:
        auth.start_login(config.effective_settings())
        return {"state": "signing_in", "error": ""}

    def auth_cancel(_payload: Dict[str, Any]) -> None:
        auth.cancel_login()

    def auth_logout(_payload: Dict[str, Any]) -> Dict[str, Any]:
        profiles.clear()
        auth.sign_out(config.effective_settings())
        return {"state": "signed_out", "error": ""}

    done: Dict[Any, Dict[str, Any]] = {}   # a profile read that has finished and has not been handed to the panel yet
    running = set()
    lock = threading.Lock()

    def read_profile(key: Any, client: FmClient) -> None:
        try:
            profile = ProfileService(client).current()   # a network read, with retries that wait: never on Fusion's thread
        except Exception:  # noqa: BLE001 - never leave the panel waiting
            profile = ProfileService(client).empty()
        if profile["user_id"] or profile["name"]:   # an answer, not the empty one a failed read gives
            profiles.put(key, profile)
        with lock:
            done[key] = profile
            running.discard(key)
        try:
            current = config.effective_settings()
        except CompanyModeUnavailable:
            return
        if (current.tenant, current.client_id) == key:   # not if the sign-in settings changed while it was read
            bridge.push("auth_profile", profile)

    def auth_profile(_payload: Dict[str, Any]) -> Dict[str, Any]:
        """The profile, or ``{"pending": True}`` while it is read in the background, which pushes it to the panels when it is done."""
        settings = config.effective_settings()
        key = (settings.tenant, settings.client_id)
        profile = profiles.get(key)
        if profile is not None:
            return profile
        with lock:
            if key in done:
                return done.pop(key)
            if key not in running:
                running.add(key)
                threading.Thread(target=read_profile, args=(key, FmClient(settings, auth)), daemon=True).start()
        return {"pending": True}

    # A browser sign-in ends on its own thread: the panel is told how it went, and does not poll while it waits.
    auth.set_on_login_done(lambda: bridge.push("auth_status", auth_status({})))

    bridge.register("auth_status", auth_status)
    bridge.register("auth_login", auth_login)
    bridge.register("auth_cancel", auth_cancel)
    bridge.register("auth_logout", auth_logout)
    bridge.register("auth_profile", auth_profile)

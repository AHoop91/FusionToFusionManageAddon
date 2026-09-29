"""Palette actions for sign-in state, login, logout and the user profile."""

from typing import Any, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import CompanyModeUnavailable, ConfigService
from ...fm.client import FmClient
from ...fm.profile import ProfileService
from ..message_bridge import MessageBridge


def register_auth_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the ``auth_*`` actions."""

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
        auth.sign_out(config.effective_settings())
        return {"state": "signed_out", "error": ""}

    def auth_profile(_payload: Dict[str, Any]) -> Dict[str, Any]:
        return ProfileService(FmClient(config.effective_settings(), auth)).current()

    bridge.register("auth_status", auth_status)
    bridge.register("auth_login", auth_login)
    bridge.register("auth_cancel", auth_cancel)
    bridge.register("auth_logout", auth_logout)
    bridge.register("auth_profile", auth_profile)

"""Palette actions for exporting and importing the configuration."""

from typing import Any, Dict

from ...config.config_service import ConfigService
from ...config.config_transfer import export_config, import_config
from ...config.models import MODE_COMPANY
from ..file_dialogs import FileDialogs
from ..message_bridge import MessageBridge
from .settings_actions import settings_payload

DEFAULT_EXPORT_NAME = "Fusion-Manage-Item-Management-config.json"


def register_transfer_actions(bridge: MessageBridge, config: ConfigService,
                              dialogs: FileDialogs) -> None:
    """Register ``export_config``, ``import_config``, ``use_shared_config`` and ``choose_shared_config``."""

    def export_action(_payload: Dict[str, Any]) -> Dict[str, Any]:
        path = dialogs.choose_save_path("Export configuration", DEFAULT_EXPORT_NAME)
        if path is None:
            return {"cancelled": True}
        export_config(config, path)
        # Someone already following a shared file has nothing to switch to.
        return {"cancelled": False, "path": path, "offer_shared": config.config.mode != MODE_COMPANY}

    def use_shared_action(payload: Dict[str, Any]) -> Dict[str, Any]:
        path = str(payload.get("path", "")).strip()
        problems = config.update(MODE_COMPANY, config.config.local, config.config.workspaces, path)
        if problems:
            raise ValueError(" ".join(problems))
        return {"path": path, "settings": settings_payload(config)}

    def import_action(_payload: Dict[str, Any]) -> Dict[str, Any]:
        path = dialogs.choose_open_path("Import configuration")
        if path is None:
            return {"cancelled": True}
        import_config(config, path)
        # Return the new settings so the panel can refill its forms.
        return {"cancelled": False, "path": path, "settings": settings_payload(config)}

    def choose_shared_action(_payload: Dict[str, Any]) -> Dict[str, Any]:
        path = dialogs.choose_open_path("Choose the shared configuration file")
        return {"cancelled": path is None, "path": path or ""}

    bridge.register("use_shared_config", use_shared_action)
    bridge.register("choose_shared_config", choose_shared_action)
    bridge.register("export_config", export_action)
    bridge.register("import_config", import_action)

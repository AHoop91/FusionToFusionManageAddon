"""Palette actions for exporting and importing the configuration."""

from typing import Any, Dict

from ...config.config_service import ConfigService
from ...config.config_transfer import export_config, import_config
from ..file_dialogs import FileDialogs
from ..message_bridge import MessageBridge
from .settings_actions import settings_payload

DEFAULT_EXPORT_NAME = "MfgToFm-config.json"


def register_transfer_actions(bridge: MessageBridge, config: ConfigService,
                              dialogs: FileDialogs) -> None:
    """Register ``export_config`` and ``import_config``."""

    def export_action(_payload: Dict[str, Any]) -> Dict[str, Any]:
        path = dialogs.choose_save_path("Export configuration", DEFAULT_EXPORT_NAME)
        if path is None:
            return {"cancelled": True}
        export_config(config, path)
        return {"cancelled": False, "path": path}

    def import_action(_payload: Dict[str, Any]) -> Dict[str, Any]:
        path = dialogs.choose_open_path("Import configuration")
        if path is None:
            return {"cancelled": True}
        import_config(config, path)
        # Return the new settings so the panel can refill its forms.
        return {"cancelled": False, "path": path, "settings": settings_payload(config)}

    bridge.register("export_config", export_action)
    bridge.register("import_config", import_action)

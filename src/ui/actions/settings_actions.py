"""Palette actions for reading and saving settings."""

from typing import Any, Dict

from ...config.config_service import ConfigService
from ...config.export_models import ExportSettings
from ...config.models import ConnectionSettings
from ...config.workspace_models import WorkspaceSettings, catalog
from ..message_bridge import MessageBridge


def settings_payload(config: ConfigService) -> Dict[str, Any]:
    """Everything the panel needs to fill its forms."""
    cfg = config.config
    return {
        "mode": cfg.mode,
        "local": cfg.local.to_dict(),
        "workspaces": cfg.workspaces.to_dict(),
        "exports": cfg.exports.to_dict(),
        "catalog": catalog(),
        "company_source": cfg.company_source,
        "callback_url": cfg.local.callback_url,
    }


def register_settings_actions(bridge: MessageBridge, config: ConfigService) -> None:
    """Register ``get_settings`` and ``save_settings``."""

    def get_settings(_payload: Dict[str, Any]) -> Dict[str, Any]:
        return settings_payload(config)

    def save_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
        local = ConnectionSettings.from_dict(payload.get("local", {}))
        workspaces = WorkspaceSettings.from_dict(payload.get("workspaces", {}))
        exports = ExportSettings.from_dict(payload["exports"]) if "exports" in payload else None
        problems = config.update(payload.get("mode", "local"), local, workspaces,
                                 str(payload.get("company_source", config.config.company_source)).strip(), exports)
        if problems:
            raise ValueError("\n".join(problems))   # one problem per line: the Settings page lists them
        return settings_payload(config)

    bridge.register("get_settings", get_settings)
    bridge.register("save_settings", save_settings)

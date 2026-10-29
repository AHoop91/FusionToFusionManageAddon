"""Palette actions for reading and saving settings."""

from dataclasses import asdict
from typing import Any, Dict, Optional

from ...config.config_service import ConfigService
from ...config.export_models import ExportSettings
from ...config.models import MODE_COMPANY, MODE_LOCAL, ConnectionSettings
from ...config.problems import problem_payload
from ...config.workspace_models import WorkspaceSettings, catalog
from ..message_bridge import MessageBridge

MODES = (MODE_LOCAL, MODE_COMPANY)
HUB_CHANGED = ("The active hub has changed since these settings were loaded. They were not saved; "
               "reopen the panel to see this hub's settings.")


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
        "shared": asdict(config.shared_status),
        "callback_url": cfg.local.callback_url,
        "hub": {"id": config.hub_id, "name": config.hub_name},   # the settings are those of this hub
        "hub_file": cfg.hub_file,   # the Configuration File in the Hub they were taken from, if they were
    }


def _section(payload: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """The part of the request called ``key``: None when the request has none (that part is left as it is), else an object.
    Raises ``ValueError`` for anything else, rather than saving defaults in its place."""
    if key not in payload:
        return None
    if not isinstance(payload[key], dict):
        raise ValueError(f"The settings could not be saved: '{key}' must be an object.")
    return payload[key]


def save_settings(config: ConfigService, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Save the settings in ``payload`` as the active hub's. A part the request leaves out stays as it is.

    Answers the settings as saved, or ``{"problems": ...}`` for the panel to mark in its fields (nothing is saved then). Raises ``ValueError``
    for a request that is not about the active hub, or is not well formed.
    """
    # The page still shows another hub's settings (or does not say which hub it shows): saving them would overwrite this one's.
    if str(payload.get("hub_id") or "") != config.hub_id:
        raise ValueError(HUB_CHANGED)
    current = config.config
    mode = str(payload.get("mode") or current.mode)
    if mode not in MODES:
        raise ValueError(f"The settings could not be saved: '{mode}' is not a mode.")
    local, workspaces, exports = (_section(payload, key) for key in ("local", "workspaces", "exports"))
    problems = config.update(
        mode,
        ConnectionSettings.from_dict(local) if local is not None else current.local,
        WorkspaceSettings.from_dict(workspaces) if workspaces is not None else current.workspaces,
        str(payload.get("company_source", current.company_source)).strip(),
        ExportSettings.from_dict(exports) if exports is not None else None)   # None keeps the export settings as they are
    if problems:
        return {"problems": problem_payload(problems)}   # the panel marks the fields they are in and lists them
    return settings_payload(config)


def register_settings_actions(bridge: MessageBridge, config: ConfigService) -> None:
    """Register ``get_settings`` and ``save_settings``."""
    bridge.register("get_settings", lambda _payload: settings_payload(config))
    bridge.register("save_settings", lambda payload: save_settings(config, payload))

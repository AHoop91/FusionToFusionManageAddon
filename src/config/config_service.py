"""Loads, saves and resolves the active connection settings.

Local mode: settings are entered by the user and stored in their profile.
Company mode: reserved. The shared-config loader is a placeholder
(``_load_company_settings``) and currently reports "not available", so the UI
can show the option without it being usable.
"""

import json
import os
from dataclasses import replace
from typing import Callable, List, Optional

from ..core.constants import ADDIN_NAME
from ..core.logging_setup import get_logger
from .models import MODE_COMPANY, MODE_LOCAL, AppConfig, ConnectionSettings
from .workspace_models import ITEMS_KIND, KINDS_BY_ID, WorkspaceSettings

log = get_logger("config")


class ConfigError(Exception):
    """The saved settings file exists but cannot be read."""


class CompanyModeUnavailable(Exception):
    """Raised when company mode is selected but cannot be resolved yet."""


def config_path() -> str:
    """Per-user config file location."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/Library/Application Support")
    folder = os.path.join(base, ADDIN_NAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "config.json")


class ConfigService:
    """Single source of truth for configuration."""

    def __init__(self, path: Optional[str] = None, tenant: Optional[Callable[[], str]] = None) -> None:
        self._path = path or config_path()
        self._tenant = tenant or (lambda: "")   # the tenant of the active Fusion hub: the only place a tenant comes from
        self._config = self._read()
        self._listeners: List[Callable[[], None]] = []

    @property
    def config(self) -> AppConfig:
        return self._config

    def on_change(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` after the settings are saved (from whichever thread saved them)."""
        self._listeners.append(callback)

    def items_setup_problem(self) -> str:
        """Why the Items workspace cannot be used yet ("" when its settings are complete)."""
        kind = KINDS_BY_ID[ITEMS_KIND]
        return self._config.workspaces.get(kind.kind_id).setup_problem(kind.title)

    def _read(self) -> AppConfig:
        """Read config from disk. A missing file is a first run (defaults); an unreadable one is an error, because
        starting from defaults would overwrite the user's settings on the next save."""
        if not os.path.exists(self._path):
            return AppConfig()
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                return AppConfig.from_dict(json.load(handle))
        except (OSError, ValueError) as exc:
            log.exception("Config unreadable")
            raise ConfigError(f"The settings file {self._path} cannot be read ({exc}). Fix or delete it, then start the add-in again.") from exc

    def save(self) -> None:
        """Persist atomically so a crash cannot leave a half-written file."""
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self._config.to_dict(), handle, indent=2)
        os.replace(tmp_path, self._path)

    def update(self, mode: str, local: ConnectionSettings,
               workspaces: WorkspaceSettings, company_source: str) -> List[str]:
        """Validate and save. Returns problems; nothing is saved if any exist.

        Local settings are only validated when local mode is active so users
        can switch modes without being blocked by unfinished fields.
        """
        problems = local.validate(require_tenant=False) if mode == MODE_LOCAL else []
        problems += workspaces.validate()
        if problems:
            return problems
        self._config = AppConfig(mode=mode, local=local, workspaces=workspaces,
                                 company_source=company_source)
        self.save()
        for callback in self._listeners:
            try:
                callback()
            except Exception:  # noqa: BLE001 - a listener must not undo a save
                log.exception("A settings listener failed")
        return []

    def effective_settings(self) -> ConnectionSettings:
        """Settings the rest of the add-in should use for the active mode."""
        if self._config.mode == MODE_COMPANY:
            return self._load_company_settings()
        return replace(self._config.local, tenant=self._tenant())

    def _load_company_settings(self) -> ConnectionSettings:
        """PLACEHOLDER: load shared company config from ``company_source``.

        Future work: fetch JSON from a UNC path or HTTPS URL, validate it, and
        merge with any user overrides for fields the company does not lock.
        """
        raise CompanyModeUnavailable("Shared Configuration is not available yet.")

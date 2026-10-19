"""Loads, saves and resolves the active configuration.

Local mode: settings are entered by the user and stored in their profile.
Shared Configuration mode: the connection, workspaces and exports come from one file on a shared path (see ``shared_config``);
only the mode and the path are stored locally. The last good copy of the file is kept, so a share that cannot be reached
for a while does not stop the add-in.
"""

import json
import os
import time
from dataclasses import dataclass, replace
from typing import Callable, List, Optional

from ..core.constants import ADDIN_NAME
from ..core.logging_setup import get_logger
from .config_envelope import ConfigTransferError
from .export_models import ExportSettings
from .hub import tenant_code
from .models import MODE_COMPANY, MODE_LOCAL, AppConfig, ConnectionSettings
from .shared_config import clean_source, read_cache, read_shared, write_cache
from .workspace_models import ITEMS_KIND, KINDS_BY_ID, WorkspaceSettings

log = get_logger("config")

SHARED_REFRESH_SECONDS = 30   # how long a read of the shared file is reused: a share can be slow, and `config` is read all the time

SHARED_OFF = "off"        # not in Shared Configuration mode
SHARED_OK = "ok"          # read from the shared file just now
SHARED_CACHED = "cached"  # the file could not be read: the last good copy is in use
SHARED_ERROR = "error"    # the file could not be read and there is no copy


class ConfigError(Exception):
    """The saved settings file exists but cannot be read."""


class CompanyModeUnavailable(Exception):
    """Raised when Shared Configuration is selected but its file cannot be read and no earlier copy exists."""


@dataclass
class SharedStatus:
    """How the shared file stands, for the Settings page."""

    state: str = SHARED_OFF
    message: str = ""


def config_path() -> str:
    """Per-user config file location."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/Library/Application Support")
    folder = os.path.join(base, ADDIN_NAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "config.json")


class ConfigService:
    """Single source of truth for configuration."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or config_path()
        self._cache_path = os.path.join(os.path.dirname(self._path), "shared_config.cache.json")
        self._stored = self._read()   # what is saved in this user's profile
        self._shared: Optional[AppConfig] = None
        self._shared_status = SharedStatus()
        self._shared_checked: Optional[float] = None
        self._listeners: List[Callable[[], None]] = []

    @property
    def config(self) -> AppConfig:
        """The configuration in use: the saved one, or in Shared Configuration mode the shared file's."""
        shared = self._shared_config()
        if shared is None:
            return self._stored
        return replace(self._stored, local=shared.local, workspaces=shared.workspaces, exports=shared.exports)

    @property
    def shared_status(self) -> SharedStatus:
        """Whether the shared file could be read (reads it again when the last read is old)."""
        self._shared_config()
        return self._shared_status

    def on_change(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` after the settings are saved (from whichever thread saved them)."""
        self._listeners.append(callback)

    def items_setup_problem(self) -> str:
        """Why the Items workspace cannot be used yet ("" when its settings are complete)."""
        kind = KINDS_BY_ID[ITEMS_KIND]
        return self.config.workspaces.get(kind.kind_id).setup_problem(kind.title)

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
            json.dump(self._stored.to_dict(), handle, indent=2)
        os.replace(tmp_path, self._path)

    def update(self, mode: str, local: ConnectionSettings,
               workspaces: WorkspaceSettings, company_source: str, exports: Optional[ExportSettings] = None) -> List[str]:
        """Validate and save. Returns problems; nothing is saved if any exist.

        Local settings are only validated when local mode is active so users can switch modes without being blocked by
        unfinished fields. In Shared Configuration mode only the mode and the path are saved, and the path must lead to a
        usable file; the other settings stay as they were, for when the user switches back. The export settings are kept
        as they are when ``exports`` is None.
        """
        if mode == MODE_COMPANY:
            try:
                read_shared(company_source)
            except ConfigTransferError as exc:
                return [str(exc)]
            self._stored = replace(self._stored, mode=mode, company_source=company_source.strip())
        else:
            exports = exports or self._stored.exports
            problems = local.validate(require_tenant=False) if mode == MODE_LOCAL else []
            problems += workspaces.validate() + exports.validate()
            if problems:
                return problems
            self._stored = AppConfig(mode=mode, local=local, workspaces=workspaces,
                                     company_source=company_source, exports=exports)
        self._shared_checked = None   # read the shared file again, as the path or mode may have changed
        self.save()
        for callback in self._listeners:
            try:
                callback()
            except Exception:  # noqa: BLE001 - a listener must not undo a save
                log.exception("A settings listener failed")
        return []

    def effective_settings(self) -> ConnectionSettings:
        """Settings the rest of the add-in should use for the active mode."""
        local = self.config.local
        if self._stored.mode == MODE_COMPANY and self._shared is None:
            raise CompanyModeUnavailable(self._shared_status.message)
        return replace(local, tenant=tenant_code(local.tenant))

    def _shared_config(self) -> Optional[AppConfig]:
        """The shared file's configuration (None outside Shared Configuration mode, or when there is neither the file nor a copy)."""
        if self._stored.mode != MODE_COMPANY:
            self._shared, self._shared_status = None, SharedStatus()
            return None
        now = time.monotonic()
        if self._shared_checked is None or now - self._shared_checked >= SHARED_REFRESH_SECONDS:
            self._shared_checked = now
            self._load_shared()
        return self._shared

    def _load_shared(self) -> None:
        """Read the shared file and keep it; when it cannot be read, fall back to the last good copy."""
        source = clean_source(self._stored.company_source)
        try:
            self._shared = read_shared(source)
        except ConfigTransferError as exc:
            log.warning("Shared configuration unreadable: %s", exc)
            cached = read_cache(self._cache_path, source)
            if cached is None:
                self._shared = None
                self._shared_status = SharedStatus(SHARED_ERROR, f"Shared Configuration is not available. {exc}")
            else:
                self._shared = cached[0]
                self._shared_status = SharedStatus(SHARED_CACHED, f"The shared file could not be read ({exc}) "
                                                   f"so the copy from {cached[1] or 'earlier'} is in use.")
            return
        self._shared_status = SharedStatus(SHARED_OK, "Read from the shared file.")
        try:
            write_cache(self._cache_path, source, self._shared)
        except OSError:
            log.exception("Could not keep a copy of the shared configuration")

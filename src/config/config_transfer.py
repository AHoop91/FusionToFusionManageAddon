"""Export and import of the add-in configuration as a JSON file.

The file wraps the normal config in a small envelope so an import can reject
files that are not ours or come from a newer version::

    {"format": "MfgToFm.config", "version": 1, "exported": "...", "config": {...}}

Only non-secret configuration is exported. Sign-in tokens are never part of
the config, so they are never written to the file. Imports go through
``ConfigService.update`` so they are validated exactly like a manual save.
"""

import json
import os
from datetime import datetime, timezone

from .config_service import ConfigService
from .models import AppConfig

FORMAT_ID = "MfgToFm.config"
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 1_000_000


class ConfigTransferError(ValueError):
    """Raised with a user-safe message when an export or import fails."""


def export_config(config: ConfigService, path: str) -> None:
    """Write the current configuration to ``path``."""
    envelope = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config.config.to_dict(),
    }
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, indent=2)
    except OSError as exc:
        raise ConfigTransferError(f"Could not write the file: {exc}") from exc


def import_config(config: ConfigService, path: str) -> None:
    """Replace the current configuration with the one in ``path``.

    Nothing changes if the file is unreadable, not ours, or fails validation.
    """
    envelope = _read_envelope(path)
    imported = AppConfig.from_dict(envelope["config"])
    problems = config.update(imported.mode, imported.local,
                             imported.workspaces, imported.company_source, imported.exports)
    if problems:
        raise ConfigTransferError("The file's settings are invalid: " + " ".join(problems))


def _read_envelope(path: str) -> dict:
    """Load and check the envelope; raise ConfigTransferError on any problem."""
    try:
        if os.path.getsize(path) > MAX_IMPORT_BYTES:
            raise ConfigTransferError("The file is too large to be a configuration.")
        with open(path, "r", encoding="utf-8") as handle:
            envelope = json.load(handle)
    except OSError as exc:
        raise ConfigTransferError(f"Could not read the file: {exc}") from exc
    except ValueError as exc:
        raise ConfigTransferError("The file is not valid JSON.") from exc

    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT_ID:
        raise ConfigTransferError("This is not an MfgToFm configuration file.")
    if envelope.get("version") != FORMAT_VERSION:
        raise ConfigTransferError(
            f"Unsupported configuration version: {envelope.get('version')}.")
    if not isinstance(envelope.get("config"), dict):
        raise ConfigTransferError("The file has no configuration data.")
    return envelope

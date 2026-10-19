"""Export and import of the add-in configuration as a JSON file.

The file format is in ``config_envelope``. Imports go through ``ConfigService.update``
so they are validated exactly like a manual save.
"""

import json
from datetime import datetime, timezone

from .config_envelope import FORMAT_ID, FORMAT_VERSION, ConfigTransferError, read_envelope
from .config_service import ConfigService
from .models import AppConfig


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
    envelope = read_envelope(path)
    imported = AppConfig.from_dict(envelope["config"])
    problems = config.update(imported.mode, imported.local,
                             imported.workspaces, imported.company_source, imported.exports)
    if problems:
        raise ConfigTransferError("The file's settings are invalid: " + " ".join(problems))

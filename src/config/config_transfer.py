"""The add-in configuration as a Configuration File: written by a Hub Admin into the Fusion Hub, read by the hub's members.

The file format is in ``config_envelope``.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from ..core.i18n import t

from .config_envelope import FORMAT_ID, FORMAT_VERSION, ConfigTransferError, parse_envelope
from .config_service import ConfigService
from .models import AppConfig

CONFIG_FILE_NAME = "Fusion-Manage-Item-Management-config.json"


def config_file_bytes(config: ConfigService, languages: Optional[Dict[str, Any]] = None) -> bytes:
    """The Configuration File for the hub ``config`` is using now, as the bytes to store, with the ``languages`` the hub shares (if any)."""
    envelope = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hub": {"id": config.hub_id, "name": config.hub_name},   # so a file is not taken for another hub's
        "config": config.config.to_dict(),
    }
    if languages:
        envelope["languages"] = languages
    return json.dumps(envelope, indent=2).encode("utf-8")


def config_from_hub_file(raw: bytes, hub_id: str, hub_name: str) -> AppConfig:
    """The configuration in a Configuration File read from the Fusion Hub, for the hub ``hub_id``.

    A file that says it was exported from another hub is refused (each hub has its own configuration); one that says nothing (older
    files) is accepted.
    """
    envelope = parse_envelope(raw)
    source = envelope.get("hub")
    source_id = str(source.get("id", "")) if isinstance(source, dict) else ""
    if source_id and hub_id and source_id != hub_id:
        origin = str(source.get("name") or t("data.config_another_hub"))
        raise ConfigTransferError(t("data.config_file_other_hub", origin=origin, hub=hub_name or t("data.config_this_hub")))
    return AppConfig.from_dict(envelope["config"])


def languages_from_hub_file(raw: bytes) -> Dict[str, Any]:
    """The languages a Configuration File shares, as written in it (``hub_languages.clean`` checks them); none for a file that has none."""
    languages = parse_envelope(raw).get("languages")
    return languages if isinstance(languages, dict) else {}

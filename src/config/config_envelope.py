"""The file format that carries a configuration: Export, Import and Shared Configuration all use it.

The configuration is wrapped in a small envelope so a reader can reject files that are not ours or come from a newer version::

    {"format": "MfgToFm.config", "version": 1, "exported": "...", "hub": {"id": "...", "name": "..."}, "config": {...}}

``hub`` says which Fusion hub the configuration was exported from (older files have none). Only non-secret configuration is written.
Sign-in tokens are never part of the config.
"""

import json
import os
from typing import Union
from ..core.i18n import t

FORMAT_ID = "MfgToFm.config"
FORMAT_VERSION = 1
MAX_CONFIG_BYTES = 2_500_000   # 2.5 MB: the settings are a few KB; the rest is room for the languages a Hub Admin shares


class ConfigTransferError(ValueError):
    """Raised with a user-safe message when a configuration file cannot be written or read."""


def parse_envelope(raw: Union[bytes, str]) -> dict:
    """Check the envelope in the file's content; raise ConfigTransferError on any problem."""
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigTransferError(t("data.config_file_too_large"))
    try:
        envelope = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
    except ValueError as exc:   # includes bytes that are not UTF-8
        raise ConfigTransferError(t("data.config_file_not_json")) from exc

    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT_ID:
        raise ConfigTransferError(t("data.config_file_not_ours"))
    if envelope.get("version") != FORMAT_VERSION:
        raise ConfigTransferError(t("data.config_file_version", version=envelope.get("version")))
    if not isinstance(envelope.get("config"), dict):
        raise ConfigTransferError(t("data.config_file_empty"))
    return envelope


def read_envelope(path: str) -> dict:
    """Load and check the envelope of the file at ``path``; raise ConfigTransferError on any problem."""
    try:
        if os.path.getsize(path) > MAX_CONFIG_BYTES:
            raise ConfigTransferError(t("data.config_file_too_large"))
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise ConfigTransferError(t("data.config_file_unreadable", reason=exc)) from exc
    return parse_envelope(raw)

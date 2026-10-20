"""The file format that carries a configuration: Export, Import and Shared Configuration all use it.

The configuration is wrapped in a small envelope so a reader can reject files that are not ours or come from a newer version::

    {"format": "MfgToFm.config", "version": 1, "exported": "...", "hub": {"id": "...", "name": "..."}, "config": {...}}

``hub`` says which Fusion hub the configuration was exported from (older files have none). Only non-secret configuration is written.
Sign-in tokens are never part of the config.
"""

import json
import os
from typing import Union

FORMAT_ID = "MfgToFm.config"
FORMAT_VERSION = 1
MAX_CONFIG_BYTES = 1_000_000


class ConfigTransferError(ValueError):
    """Raised with a user-safe message when a configuration file cannot be written or read."""


def parse_envelope(raw: Union[bytes, str]) -> dict:
    """Check the envelope in the file's content; raise ConfigTransferError on any problem."""
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigTransferError("The file is too large to be a configuration.")
    try:
        envelope = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
    except ValueError as exc:   # includes bytes that are not UTF-8
        raise ConfigTransferError("The file is not valid JSON.") from exc

    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT_ID:
        raise ConfigTransferError("This is not an MfgToFm configuration file.")
    if envelope.get("version") != FORMAT_VERSION:
        raise ConfigTransferError(
            f"Unsupported configuration version: {envelope.get('version')}.")
    if not isinstance(envelope.get("config"), dict):
        raise ConfigTransferError("The file has no configuration data.")
    return envelope


def read_envelope(path: str) -> dict:
    """Load and check the envelope of the file at ``path``; raise ConfigTransferError on any problem."""
    try:
        if os.path.getsize(path) > MAX_CONFIG_BYTES:
            raise ConfigTransferError("The file is too large to be a configuration.")
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise ConfigTransferError(f"Could not read the file: {exc}") from exc
    return parse_envelope(raw)

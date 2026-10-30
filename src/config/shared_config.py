"""The configuration an organisation shares as one file on a network path or shared folder.

The file is an exported configuration (see ``config_envelope``): set the add-in up on one machine, use Export, and put the file
where everyone can read it. Reading the shared file is the only thing this module does; ``ConfigService`` decides when.
"""

import json
import os
from datetime import datetime
from typing import Optional

from .config_envelope import ConfigTransferError, read_envelope
from .models import AppConfig

NO_SOURCE = "No shared configuration file is set."
NOT_ABSOLUTE = "The shared configuration file must be given as a full path, such as C:\\Share\\config.json or \\\\server\\share\\config.json."


def read_shared(source: str) -> AppConfig:
    """Read and validate the shared configuration at ``source``; raise ConfigTransferError when it cannot be used."""
    source = clean_source(source)
    if not source:
        raise ConfigTransferError(NO_SOURCE)
    if not os.path.isabs(source):   # a relative path would be read from wherever Fusion happens to be running
        raise ConfigTransferError(NOT_ABSOLUTE)
    shared = AppConfig.from_dict(read_envelope(source)["config"])
    # The tenant may be left out, as for a saved local setup: it is found on the first sign-in.
    problems = shared.local.validate(require_tenant=False) + shared.workspaces.validate() + shared.exports.validate()
    if problems:
        raise ConfigTransferError("The shared configuration is invalid: " + " ".join(problems))
    return shared


def clean_source(source: str) -> str:
    """The path as typed, without the quotes Windows adds when copying a path. Nothing is expanded: ``~`` and ``%VARIABLES%`` are not read, so
    the file read is the one the user can see in the box, whatever Fusion's environment holds."""
    return source.strip().strip('"')


def write_cache(path: str, source: str, shared: AppConfig) -> None:
    """Keep the last good copy so the add-in still works when the share is unreachable. Atomic, like the main settings."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump({"source": source, "saved": datetime.now().isoformat(timespec="seconds"), "config": shared.to_dict()}, handle, indent=2)
    os.replace(tmp_path, path)


def read_cache(path: str, source: str) -> Optional[tuple]:
    """The copy kept for ``source`` as (configuration, date saved), or None when there is none, it is for another file, or it is unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("source") != source:
            return None
        return AppConfig.from_dict(data["config"]), str(data.get("saved", ""))[:10]
    except (OSError, ValueError, KeyError, AttributeError):
        return None

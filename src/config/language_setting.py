"""The language the user chose for the add-in's panels.

It belongs to the user, not to a hub: it is kept in a file of its own beside the settings, and never goes into a hub's Configuration File,
so choosing a language does not change what a Hub Admin saved for everyone. It can be read and changed signed out.
"""

import json
import os
from typing import Optional

from ..core.atomic import write_atomically
from ..core.i18n import DEFAULT_LANGUAGE
from ..core.logging_setup import get_logger
from ..core.paths import DataDirError, data_dir

log = get_logger("language")

FILE_NAME = "language.json"


def _path(folder: Optional[str]) -> Optional[str]:
    if folder is not None:
        return os.path.join(folder, FILE_NAME)
    try:
        return os.path.join(data_dir(roaming=True), FILE_NAME)
    except DataDirError:
        return None


def read_language(folder: Optional[str] = None) -> str:
    """The code the user chose, or English when none was chosen or the file cannot be read. ``folder`` is the settings folder."""
    path = _path(folder)
    if not path or not os.path.exists(path):
        return DEFAULT_LANGUAGE
    try:
        with open(path, "r", encoding="utf-8") as handle:
            code = json.load(handle).get("language")
    except (OSError, ValueError, AttributeError) as exc:
        log.warning("The language setting cannot be read (%s); English is used", exc)
        return DEFAULT_LANGUAGE
    return code.strip() if isinstance(code, str) and code.strip() else DEFAULT_LANGUAGE


def write_language(code: str, folder: Optional[str] = None) -> None:
    """Keep ``code`` as the user's choice. Raises ``OSError`` when it cannot be kept (the settings folder is not known, or not writable)."""
    path = _path(folder)
    if not path:
        raise DataDirError("The settings folder is not known, so the language cannot be kept.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_atomically(path, json.dumps({"language": code}, indent=2).encode("utf-8"))

"""Where the add-in keeps its files: the user's application-data folders, and the system's temporary folder, and nowhere else.

On Windows the folders come from ``%LOCALAPPDATA%`` (tokens, logs, remembered item numbers) and ``%APPDATA%`` (the settings). When the
variable is missing or not an absolute path there is no fallback to the user's home folder: the caller is told, and keeps nothing.
"""

import os
import sys
import tempfile

from .constants import ADDIN_NAME

MAC_DATA = "~/Library/Application Support"
MAC_LOGS = "~/Library/Logs"


class DataDirError(OSError):
    """The folder the add-in keeps its files in cannot be told."""


def _base(variable: str, mac: str) -> str:
    if sys.platform == "win32":
        base = os.environ.get(variable, "").strip()
        if not os.path.isabs(base):
            raise DataDirError(f"%{variable}% is not set to a folder, so the add-in has nowhere to keep its files.")
        return base
    base = os.path.expanduser(mac)
    if not os.path.isabs(base):   # no home folder is known: ``~`` is left as it is, and would mean wherever Fusion happens to be running
        raise DataDirError("The home folder is not known, so the add-in has nowhere to keep its files.")
    return base


def data_dir(roaming: bool = False) -> str:
    """The add-in's folder in the user's application data: ``%APPDATA%`` when ``roaming`` (the settings), else ``%LOCALAPPDATA%``.
    Raises ``DataDirError`` when the variable is not usable."""
    return os.path.join(_base("APPDATA" if roaming else "LOCALAPPDATA", MAC_DATA), ADDIN_NAME)


def log_dir() -> str:
    """The user's log folder for the add-in. Raises ``DataDirError`` when ``%LOCALAPPDATA%`` is not usable."""
    if sys.platform == "win32":
        return os.path.join(data_dir(), "logs")
    return os.path.join(_base("", MAC_LOGS), ADDIN_NAME, "logs")


def temp_dir() -> str:
    """The add-in's own folder in the system's temporary folder."""
    return os.path.join(tempfile.gettempdir(), ADDIN_NAME)


def inside_temp(path: str) -> bool:
    """Is ``path`` an absolute path in the system's temporary folder, by real path (``..`` and links do not lead out of it)?"""
    if not path or not os.path.isabs(path):
        return False
    root = os.path.realpath(tempfile.gettempdir())
    try:
        return os.path.commonpath([root, os.path.realpath(path)]) == root
    except ValueError:   # another drive
        return False

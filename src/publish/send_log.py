"""What a send did, kept on disk in the publish folder: ``send-log.json``.

Sending a folder again skips what the log holds as accepted, so nothing is created twice. Each request is logged the moment it is
accepted, and one that a cancel cut off is logged as in doubt: it may or may not have been done, so a send finds out before it sends it
again (see ``sender``).
"""

import json
import os
from typing import Any, Dict

from ..core.atomic import write_atomically
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict

log = get_logger("publish_send")

SEND_LOG = "send-log.json"
IN_DOUBT = {"in_doubt": True}   # what the log holds for a write that was cut off


class FolderError(Exception):
    """The chosen folder is not a publish folder this version can send."""


class LogWriteError(OSError):
    """The log could not be written. Whatever was sent since it last was is not in it, so sending the folder again could send it twice."""


def load_log(folder: str) -> Dict[str, Any]:
    """What an earlier send did. No log is a folder never sent; an unreadable one is an error, since sending on
    without it would create the items again."""
    file = os.path.join(folder, SEND_LOG)
    if not os.path.exists(file):
        return {}
    try:
        with open(file, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FolderError(f"Could not read {SEND_LOG}: {exc}. Sending without it could create items twice.") from exc
    if not isinstance(data, dict):
        raise FolderError(f"{SEND_LOG} is not a send log. Sending without it could create items twice.")
    return data


class SendLog:
    """The requests of a folder that were sent, by key (``item:<number>``, ``bom:<parent>:<index>``), each with what came of it.

    Not safe to use from several threads at once: the caller holds a lock around it.
    """

    def __init__(self, folder: str) -> None:
        self._file = os.path.join(folder, SEND_LOG)
        self._entries: Dict[str, Any] = load_log(folder)

    def done(self, key: str) -> bool:
        """Whether the request under ``key`` was accepted (one that was cut off is logged too, but is not done)."""
        return key in self._entries and not self.in_doubt(key)

    def in_doubt(self, key: str) -> bool:
        """Whether the request under ``key`` was cut off by a cancel, and may or may not have been done."""
        return bool(self.entry(key).get("in_doubt"))

    def entry(self, key: str) -> Dict[str, Any]:
        """What the log holds for ``key`` ({} for a request not logged)."""
        return as_dict(self._entries.get(key))

    def accept(self, key: str, entry: Dict[str, Any]) -> None:
        """Log on disk, before going on, that the request under ``key`` was accepted (``entry``: what it made, such as the new item's id), so a
        crash or cancel cannot make a resend duplicate it."""
        self._entries[key] = entry
        self._write()

    def doubt(self, key: str, why: str) -> None:
        """Log that the write under ``key`` may or may not have been done (``why``: it was cancelled while being sent, it got no answer)."""
        log.warning("%s %s: it may or may not have been done", key, why)
        self.accept(key, dict(IN_DOUBT))

    def intend(self, key: str) -> None:
        """Log on disk, before the request under ``key`` is sent, that it is about to be: a crash after the server made something but before
        ``accept`` leaves this, which is read as in doubt, so a resend finds out whether it was done before sending it again."""
        self.accept(key, dict(IN_DOUBT))

    def forget(self, key: str) -> None:
        """Take back what ``intend`` logged, for a request that was refused (so it was not done). If the log cannot be written the entry stays
        on disk as in doubt, which only costs the next send a look in Fusion Manage."""
        self._entries.pop(key, None)
        try:
            self._write()
        except LogWriteError as exc:
            log.warning("%s was refused but the log still holds it as in doubt: %s", key, exc)

    def _write(self) -> None:
        """Write the entries to the log file, whole, so a crash leaves the old log or the new one and never half of one. A log that cannot be
        written is raised as ``LogWriteError``: a request accepted since the last write would be sent again by the next send."""
        try:
            write_atomically(self._file, json.dumps(self._entries, indent=2).encode("utf-8"))
        except OSError as exc:
            raise LogWriteError(f"The send log could not be written ({exc}). Check Fusion Manage before sending this folder again: "
                                f"what was sent since may be sent twice.") from exc

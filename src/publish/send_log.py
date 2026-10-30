"""What a send did, kept on disk in the publish folder: ``send-log.json``.

Sending a folder again skips what the log holds as accepted, so nothing is created twice. Each request is logged the moment it is
accepted, and one that a cancel cut off is logged as in doubt: it may or may not have been done, so a send finds out before it sends it
again (see ``sender``).

Requests are sent together, and each is logged on disk before the send goes on, so the log is written often. The writes are not made one
after the other: what is logged while a write is under way is carried by the next one, which every thread waiting for it shares (see
``_flush``). Slow storage, or a scanner holding the file, then costs a few writes, not one for each request.
"""

import json
import os
import threading
from typing import Any, Dict, Optional

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

    Any thread may use it, and none needs a lock of its own around it: the caller must not hold one while it logs, or the writes of requests
    sent together would wait for one another.
    """

    def __init__(self, folder: str) -> None:
        self._file = os.path.join(folder, SEND_LOG)
        self._entries: Dict[str, Any] = load_log(folder)
        self._lock = threading.Lock()   # guards the entries and the two counters
        self._io = threading.Lock()   # one write of the file at a time
        self._version = 0   # counts the changes made to the entries
        self._written = 0   # the version the file holds

    def done(self, key: str) -> bool:
        """Whether the request under ``key`` was accepted (one that was cut off is logged too, but is not done)."""
        with self._lock:
            return key in self._entries and not bool(as_dict(self._entries[key]).get("in_doubt"))

    def in_doubt(self, key: str) -> bool:
        """Whether the request under ``key`` was cut off by a cancel, and may or may not have been done."""
        return bool(self.entry(key).get("in_doubt"))

    def entry(self, key: str) -> Dict[str, Any]:
        """What the log holds for ``key`` ({} for a request not logged)."""
        with self._lock:
            return dict(as_dict(self._entries.get(key)))

    def accept(self, key: str, entry: Dict[str, Any]) -> None:
        """Log on disk, before going on, that the request under ``key`` was accepted (``entry``: what it made, such as the new item's id), so a
        crash or cancel cannot make a resend duplicate it."""
        self._flush(self._record(key, entry))

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
        try:
            self._flush(self._record(key, None))
        except LogWriteError as exc:
            log.warning("%s was refused but the log still holds it as in doubt: %s", key, exc)

    def _record(self, key: str, entry: Optional[Dict[str, Any]]) -> int:
        """Change the entries (``entry`` None takes ``key`` out) and say which version of them that makes."""
        with self._lock:
            if entry is None:
                self._entries.pop(key, None)
            else:
                self._entries[key] = entry
            self._version += 1
            return self._version

    def _flush(self, version: int) -> None:
        """Return once the file holds ``version`` of the entries or a later one. The write is of the whole log, so every change made before it
        begins is in it: a thread that finds, once it may write, that a write begun after its change has finished has nothing left to do.
        A log that cannot be written is raised as ``LogWriteError``: a request accepted since the last write would be sent again by the next
        send."""
        with self._io:
            with self._lock:
                if self._written >= version:
                    return
                covering = self._version
                data = json.dumps(self._entries, indent=2).encode("utf-8")
            try:
                write_atomically(self._file, data)
            except OSError as exc:
                raise LogWriteError(f"The send log could not be written ({exc}). Check Fusion Manage before sending this folder again: "
                                    f"what was sent since may be sent twice.") from exc
            with self._lock:
                self._written = covering

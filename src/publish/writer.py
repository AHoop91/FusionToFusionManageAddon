"""The output folder of one publish run and its ``manifest.json``.

Every artifact (item request, thumbnail, BOM requests) gets an entry in
the manifest saying whether it was written, skipped or failed and why, so a run can be
reviewed from the folder alone. A failed artifact never stops the run.
"""

import json
import os
import re
import threading
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Set

from ..core.atomic import write_atomically

OK, SKIPPED, FAILED = "ok", "skipped", "error"
NAME_CHARS = 80   # of a name made for a file or folder
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_DEVICES = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))})   # not files on Windows


def safe_name(text: str, fallback: str = "item") -> str:
    """A file or folder name from ``text``: no path characters, no trailing dots or spaces, not a device name, not empty."""
    name = _UNSAFE.sub("_", str(text or ""))[:NAME_CHARS].strip(" .")
    if name.split(".")[0].upper() in _DEVICES:   # ``CON`` and ``con.step`` are the console on Windows, whatever the extension
        name = "_" + name
    return name or fallback


def _by_status(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    return dict(Counter(entry["status"] for entry in entries))


class PublishFolder:
    """``<parent>/<root item>_<time>/`` with the files of one run. Items are prepared on several threads: what they record is kept under a lock."""

    def __init__(self, parent: str, root_number: str) -> None:
        self.path = self._create(parent, f"{safe_name(root_number, 'design')}_{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        self.entries: List[Dict[str, Any]] = []
        self.items: Dict[str, Dict[str, str]] = {}   # item number -> {"id", "state", "request"}: what sending needs to find each item
        self._used: Set[str] = set()   # the folder names given to items, in lower case (a name is one on a filesystem that ignores case)
        self._lock = threading.Lock()

    @staticmethod
    def _create(parent: str, name: str) -> str:
        """Make the folder of this run. Runs of one design started within a second have one name: the later ones are numbered."""
        for count in range(1, 1000):
            path = os.path.join(parent, name if count == 1 else f"{name}_{count}")
            try:
                os.makedirs(path)
                return path
            except FileExistsError:
                continue
        raise FileExistsError(f"There are too many folders called {name} in {parent}.")

    def item_dir(self, number: str) -> str:
        """Folder of one item, unique within the run even when two numbers make the same name, or one is named like the other's number."""
        name = safe_name(number)
        with self._lock:
            candidate, count = name, 1
            while candidate.lower() in self._used:
                count += 1
                candidate = f"{name}_{count}"
            self._used.add(candidate.lower())
        return os.path.join("items", candidate)

    def path_of(self, relative: str) -> str:
        """The full path of a file of the run (``relative`` to its folder), with the folders to it made."""
        full = os.path.join(self.path, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full

    def write_json(self, relative: str, data: Any) -> str:
        """Write ``data`` as the whole of a JSON file of the run; returns its path."""
        return self.write_bytes(relative, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def write_bytes(self, relative: str, data: bytes) -> str:
        """Write ``data`` as the whole of a file of the run; returns its path."""
        full = self.path_of(relative)
        write_atomically(full, data)
        return full

    def record(self, item: str, artifact: str, status: str, detail: str = "", file: str = "") -> Dict[str, Any]:
        """Note what became of one artifact of an item (or Bill of Materials parent): ``status`` is ``OK``, ``SKIPPED`` or ``FAILED``."""
        entry = {"item": item, "artifact": artifact, "status": status, "detail": detail, "file": file}
        with self._lock:
            self.entries.append(entry)
        return entry

    def set_item(self, number: str, info: Dict[str, str]) -> None:
        """Note what sending needs to find an item: its ``id``, its ``state`` in Fusion Manage and its ``request`` file."""
        with self._lock:
            self.items[number] = info

    def entries_of(self, item: str) -> List[Dict[str, Any]]:
        """The entries recorded for one item (or Bill of Materials parent)."""
        with self._lock:
            return [entry for entry in self.entries if entry["item"] == item]

    def counts(self) -> Dict[str, int]:
        """How many entries have each status."""
        with self._lock:
            return _by_status(self.entries)

    def save_manifest(self, info: Dict[str, Any]) -> None:
        """Write ``manifest.json``: ``info`` about the run, then what was recorded of it."""
        with self._lock:
            items, entries = dict(self.items), list(self.entries)
        manifest = {"draft": True,
                    "note": "Requests are drafts for review: bodies follow the Fusion Manage v3 API but are unverified. "
                            "A publish sends them as it goes; Retry in the Job Queue sends the folder again, and send-log.json records what Fusion Manage accepted.",
                    **info, "counts": _by_status(entries), "items": items, "artifacts": entries}
        self.write_json("manifest.json", manifest)

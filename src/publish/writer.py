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
from typing import Any, Dict, List

OK, SKIPPED, FAILED = "ok", "skipped", "error"
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_name(text: str, fallback: str = "item") -> str:
    """A file or folder name from ``text``: no path characters, no trailing dots or spaces, not empty."""
    name = _UNSAFE.sub("_", str(text or "")).strip(" .")
    return name[:80] or fallback


class PublishFolder:
    """``<parent>/<root item>_<time>/`` with the files of one run."""

    def __init__(self, parent: str, root_number: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(parent, f"{safe_name(root_number, 'design')}_{stamp}")
        os.makedirs(self.path)
        self.entries: List[Dict[str, Any]] = []
        self.items: Dict[str, Dict[str, str]] = {}   # item number -> {"id", "state", "request"}: what sending needs to find each item
        self._names: Dict[str, int] = {}
        self._lock = threading.Lock()   # items are prepared on several threads

    def item_dir(self, number: str) -> str:
        """Folder of one item, unique within the run even when two numbers sanitise to the same name."""
        name = safe_name(number)
        with self._lock:
            count = self._names.get(name.lower(), 0)
            self._names[name.lower()] = count + 1
        return os.path.join("items", name if not count else f"{name}_{count + 1}")

    def path_of(self, relative: str) -> str:
        full = os.path.join(self.path, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full

    def write_json(self, relative: str, data: Any) -> str:
        full = self.path_of(relative)
        with open(full, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        return full

    def write_bytes(self, relative: str, data: bytes) -> str:
        full = self.path_of(relative)
        with open(full, "wb") as handle:
            handle.write(data)
        return full

    def record(self, item: str, artifact: str, status: str, detail: str = "", file: str = "") -> Dict[str, Any]:
        entry = {"item": item, "artifact": artifact, "status": status, "detail": detail, "file": file}
        with self._lock:
            self.entries.append(entry)
        return entry

    def counts(self) -> Dict[str, int]:
        """How many entries have each status."""
        with self._lock:
            return dict(Counter(entry["status"] for entry in self.entries))

    def save_manifest(self, info: Dict[str, Any]) -> None:
        manifest = {"draft": True,
                    "note": "Requests are drafts for review: bodies follow the Fusion Manage v3 API but are unverified. "
                            "A publish sends them as it goes; sending the folder again retries, and send-log.json records what Fusion Manage accepted.",
                    **info, "counts": self.counts(), "items": self.items, "artifacts": self.entries}
        self.write_json("manifest.json", manifest)

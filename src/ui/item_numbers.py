"""The Item Number of a component, from the Manufacturing Data Model.

Fusion's API gives a component only its part number, and a part number need not match its item number. The item number is
what Fusion Manage knows an item by, so it is read from the Data Model: the design's own from its summary, a component below it
from the design's bill of materials (read once per version of the design and kept). A component with no item number has not
been published, so it is refused with ``NoItemNumber``.
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
from ..core.constants import ADDIN_NAME
from ..core.logging_setup import get_logger
from ..fusion_mfg.graphql_client import MfgGraphQlClient
from ..fusion_mfg.model_service import read_section

log = get_logger("item_numbers")


class NoItemNumber(Exception):
    """The component has no item number in the Data Model (or it cannot be told which), so it is not published."""


class DesignRef(NamedTuple):
    """Which version of which design to read: ``model_id`` and ``time`` as the Publish panel uses them."""

    model_id: str
    time: str


class Subject(NamedTuple):
    """A component as Fusion Manage and Fusion each name it."""

    item_number: str   # what Fusion Manage finds the item by
    part_number: str   # what Fusion calls the component, to find it in the open design


def design_ref(design: Any) -> DesignRef:
    """The Data Model id and version of ``design`` (empty when it has none: it is not saved). UI thread."""
    data = design.rootDataComponent if design is not None else None
    return DesignRef(str(data.mfgdmModelId or ""), str(data.timestamp or "")) if data is not None else DesignRef("", "")


def active_design_ref() -> DesignRef:
    """The reference of the open design. UI thread."""
    return design_ref(adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct))


def _same(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


class _Remembered:
    """Item numbers already found, kept in a file so they outlast Fusion. A saved version of a design never changes, so what was read for
    ``(model_id, time, part number)`` is still true. Only found numbers are kept; a missing one may be given later. Failures to read or write
    the file are logged and otherwise ignored: the Data Model is asked instead."""

    LIMIT = 1000   # entries kept; the oldest go first

    def __init__(self, path: str) -> None:
        self._path = path
        self._entries: Dict[str, List[str]] = self._load()

    @staticmethod
    def _key(ref: DesignRef, part_number: str) -> str:
        return f"{ref.model_id}|{ref.time}|{part_number.strip().lower()}"

    def _load(self) -> Dict[str, List[str]]:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if isinstance(v, list) and len(v) == 2}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Item numbers kept from earlier are not read: %s", exc)
            return {}

    def get(self, ref: DesignRef, part_number: str) -> Optional[Subject]:
        found = self._entries.get(self._key(ref, part_number))
        return Subject(found[0], found[1]) if found else None

    def add(self, ref: DesignRef, part_number: str, subject: Subject) -> None:
        key = self._key(ref, part_number)
        self._entries.pop(key, None)   # re-added last, so it is the newest
        self._entries[key] = [subject.item_number, subject.part_number]
        while len(self._entries) > self.LIMIT:
            del self._entries[next(iter(self._entries))]
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._entries, f)
        except OSError as exc:
            log.warning("Item numbers are not kept for next time: %s", exc)


def _remembered_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/Library/Application Support")
    return os.path.join(base, ADDIN_NAME, "item_numbers.json")


class ItemNumbers:
    """Finds item numbers; the reads run on a worker thread, never on Fusion's."""

    def __init__(self, config: ConfigService, auth: AuthService, remembered_path: Optional[str] = None) -> None:
        self._config = config
        self._auth = auth
        self._remembered = _Remembered(remembered_path or _remembered_path())
        self._lock = threading.Lock()
        self._key: Tuple[str, str] = ("", "")
        self._summary: Dict[str, Any] = {}
        self._rows: Any = None   # the bill of materials of ``_key``, once read

    def resolve(self, ref: DesignRef, part_number: str) -> Subject:
        """The ``Subject`` of the component with ``part_number`` in the design ``ref`` ("" is the design itself). Worker thread."""
        if not ref.model_id:
            raise NoItemNumber("The design has not been saved, so it has no item number.")
        requested = part_number
        known = self._remembered.get(ref, requested)
        if known:
            log.info("Part number %s is item number %s (kept from an earlier read)", known.part_number or "(the design)", known.item_number)
            return known
        began = time.monotonic()
        client =MfgGraphQlClient(self._config.effective_settings(), self._auth)
        with self._lock:   # one read at a time, so a burst of selections reads the bill of materials once
            if self._key != tuple(ref):
                self._key, self._summary, self._rows = tuple(ref), read_section(client, "summary", ref.model_id, ref.time), None
            summary = self._summary
            top_part = str(summary.get("part_number") or "")
            if not part_number or _same(part_number, top_part):
                found, part_number = {str(summary.get("item_number") or "")}, top_part
            else:
                if self._rows is None:
                    self._rows = read_section(client, "structure", ref.model_id, ref.time, summary)
                found = {str(r["item_number"]) for r in self._rows if _same(str(r["part_number"]), part_number)}
        label = part_number or "The design"
        if not found:
            raise NoItemNumber(f"{label} was not found in the Data Model's bill of materials of the open design.")
        if len(found) > 1:
            raise NoItemNumber(f"Part number {part_number} has more than one item number in this design, so which item it is cannot be told.")
        number = found.pop().strip()
        if not number:
            raise NoItemNumber(f"{label} has no item number, so it has not been published to Fusion Manage.")
        log.info("Part number %s is item number %s (%.2fs; the Data Model is read once per version of the design, then kept)",
                 part_number or "(the design)", number, time.monotonic() - began)
        subject = Subject(number, part_number)
        self._remembered.add(ref, requested, subject)
        return subject

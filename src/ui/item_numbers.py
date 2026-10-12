"""The Item Number of a component, from the Manufacturing Data Model.

Fusion's API gives a component only its part number, and a part number need not match its item number. The item number is
what Fusion Manage knows an item by, so it is read from the Data Model: the design's own from its summary, a component below it
from the design's bill of materials (read once per version of the design and kept). A component with no item number has not
been published, so it is refused with ``NoItemNumber``.
"""

import threading
from typing import Any, Dict, NamedTuple, Tuple

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
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


class ItemNumbers:
    """Finds item numbers; the reads run on a worker thread, never on Fusion's."""

    def __init__(self, config: ConfigService, auth: AuthService) -> None:
        self._config = config
        self._auth = auth
        self._lock = threading.Lock()
        self._key: Tuple[str, str] = ("", "")
        self._summary: Dict[str, Any] = {}
        self._rows: Any = None   # the bill of materials of ``_key``, once read

    def resolve(self, ref: DesignRef, part_number: str) -> Subject:
        """The ``Subject`` of the component with ``part_number`` in the design ``ref`` ("" is the design itself). Worker thread."""
        if not ref.model_id:
            raise NoItemNumber("The design has not been saved, so it has no item number.")
        client = MfgGraphQlClient(self._config.effective_settings(), self._auth)
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
        log.info("Part number %s is item number %s", part_number or "(the design)", number)
        return Subject(number, part_number)

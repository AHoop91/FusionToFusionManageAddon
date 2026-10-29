"""Fits the text a property holds to the Fusion Manage field it is sent to.

A picklist or radio field takes a link to one of its lookup's options (``/api/v3/lookups/<name>/options/6``),
not the option's title, so a mapped text such as "Top Level Assembly" has to be found among the options first.
A number field refuses more decimal digits than its ``fieldPrecision``, so a number is rounded to fit.
A field with a unit of measure takes its number in that unit, so a number in another unit is converted.
"""

import math
import threading
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ..auth.errors import AuthError
from ..core.logging_setup import get_logger
from ..core.shapes import rows_in
from ..core.units import convert
from .client import WORKSPACES, FmApiError, FmClient, last_segment
from .ttl_cache import TtlCache
from .workspace import WorkspaceService

log = get_logger("fm.picklists")


class FieldFacts(NamedTuple):
    """What a workspace's field list says about how its fields take a value, each by field id."""

    lookups: Dict[str, str]   # the lookup behind a fixed-list field
    precisions: Dict[str, int]   # the most decimal digits a number field takes
    units: Dict[str, str]   # the unit of measure a field is set to


_facts_cache = TtlCache()   # workspace id -> FieldFacts, so the panel and a run read the fields once


def parse_fields(data: Any) -> FieldFacts:
    """The ``FieldFacts`` of the answer listing a workspace's fields. A field that links to another workspace (it has a picklist field
    definition) is not a fixed list."""
    lookups: Dict[str, str] = {}
    precisions: Dict[str, int] = {}
    units: Dict[str, str] = {}
    for row in rows_in(data, "fields"):
        field = last_segment(row.get("__self__"))
        precision = row.get("fieldPrecision")
        if isinstance(precision, int) and not isinstance(precision, bool):
            precisions[field] = precision
        if row.get("picklist") and not row.get("picklistFieldDefinition"):
            lookups[field] = last_segment(row["picklist"])
        if row.get("unitOfMeasure"):
            units[field] = str(row["unitOfMeasure"])
    return FieldFacts(lookups, precisions, units)


class PicklistResolver:
    """Fits values to the fields of one workspace: the options of its picklists (each read once), the units and precision of its numbers.
    The resolver is shared by a run's threads."""

    def __init__(self, client: FmClient, workspace_id: str) -> None:
        self._client = client
        self._workspace_id = workspace_id
        self._lock = threading.Lock()
        self._options: Dict[str, List[Dict[str, str]]] = {}   # lookup name -> [{value: link, title}]

    def _facts(self) -> FieldFacts:
        """The facts about the workspace's fields, read once. Empty when they cannot be read, and then not remembered, so the next
        field tries again."""
        known = _facts_cache.get(self._workspace_id)
        if known is not None:
            return known
        try:
            data = self._client.get_json(f"{WORKSPACES}/{self._workspace_id}/fields")
        except (FmApiError, AuthError) as exc:
            log.warning("Could not read the fields of workspace %s: %s", self._workspace_id, exc)
            return FieldFacts({}, {}, {})
        return _facts_cache.put(self._workspace_id, parse_fields(data))

    def link(self, field_id: str, text: str) -> Optional[str]:
        """The link of the option titled ``text`` (ignoring case) in the field's picklist.

        "" when the field is a picklist but has no such option; None when it is not a picklist."""
        with self._lock:
            lookup = self._facts().lookups.get(field_id, "")
            if not lookup:
                return None
            if lookup not in self._options:
                self._options[lookup] = WorkspaceService(self._client).options(lookup)
            wanted = text.strip().lower()
            return next((o["value"] for o in self._options[lookup] if o["title"].strip().lower() == wanted), "")

    def convert_unit(self, field_id: str, text: str, unit: str) -> Optional[Tuple[str, str]]:
        """``text``, a number in ``unit``, as ``(number, unit)`` in the unit the field is set to ("mm", "kilograms").

        None when the field states no unit, or its unit is not one that ``unit`` converts to; the number is then not changed.
        """
        with self._lock:
            target = self._facts().units.get(field_id, "")
        if not target:
            return None
        try:
            number = float(text.strip())
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        converted = convert(number, unit, target)
        if converted is None:
            log.warning("Field %s is in %r, which %r does not convert to; sent as it is", field_id, target, unit)
            return None
        return f"{converted:.8g}", target

    def fit_number(self, field_id: str, text: str) -> str:
        """``text`` rounded to the decimal digits the field takes (unchanged when it is not a number or the field states no limit)."""
        with self._lock:
            digits = self._facts().precisions.get(field_id)
        if digits is None:
            return text
        try:
            number = Decimal(text.strip())
        except InvalidOperation:
            return text
        if not number.is_finite():
            return text
        return format(number.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP).normalize(), "f")

"""Fits the text a property holds to the Fusion Manage field it is sent to.

A picklist or radio field takes a link to one of its lookup's options (``/api/v3/lookups/<name>/options/6``),
not the option's title, so a mapped text such as "Top Level Assembly" has to be found among the options first.
A number field refuses more decimal digits than its ``fieldPrecision``, so a number is rounded to fit.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import threading
from typing import Dict, List, Optional, Tuple

from ..auth.errors import AuthError
from ..core.units import convert
from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmApiError, FmClient, last_segment
from .ttl_cache import TtlCache
from .workspace import WorkspaceService

log = get_logger("fm.picklists")

_fields_cache = TtlCache()   # workspace id -> (field id -> lookup name, field id -> decimal digits, field id -> unit), so the panel and a run read the fields once


class PicklistResolver:
    """The options of the picklist fields of one workspace, each read once (the resolver is shared by a run's threads)."""

    def __init__(self, client: FmClient, workspace_id: str) -> None:
        self._client = client
        self._workspace_id = workspace_id
        self._lock = threading.Lock()
        self._lookups: Optional[Dict[str, str]] = None   # field id -> lookup name
        self._precisions: Dict[str, int] = {}   # field id -> most decimal digits it takes
        self._units: Dict[str, str] = {}   # field id -> the unit of measure it is set to
        self._options: Dict[str, List[Dict[str, str]]] = {}   # lookup name -> [{value: link, title}]

    def _lookup_of(self, field_id: str) -> str:
        """The lookup behind a fixed-list field ("" for any other field, or one that links to another workspace)."""
        if self._lookups is None:
            known = _fields_cache.get(self._workspace_id)
            if known is None:
                lookups: Dict[str, str] = {}
                precisions: Dict[str, int] = {}
                units: Dict[str, str] = {}
                try:
                    data = self._client.get_json(f"{WORKSPACES}/{self._workspace_id}/fields")
                except (FmApiError, AuthError) as exc:
                    log.warning("Could not read the fields of workspace %s: %s", self._workspace_id, exc)
                    return ""   # not remembered, so the next field tries again
                rows = data.get("fields") if isinstance(data, dict) else data
                for row in rows if isinstance(rows, list) else []:
                    if isinstance(row, dict) and isinstance(row.get("fieldPrecision"), int) and not isinstance(row["fieldPrecision"], bool):
                        precisions[last_segment(row.get("__self__"))] = row["fieldPrecision"]
                    if isinstance(row, dict) and row.get("picklist") and not row.get("picklistFieldDefinition"):
                        lookups[last_segment(row.get("__self__"))] = last_segment(row["picklist"])
                    if isinstance(row, dict) and row.get("unitOfMeasure"):
                        units[last_segment(row.get("__self__"))] = str(row["unitOfMeasure"])
                known = _fields_cache.put(self._workspace_id, (lookups, precisions, units))
            self._lookups, self._precisions, self._units = known
        return self._lookups.get(field_id, "")

    def link(self, field_id: str, text: str) -> Optional[str]:
        """The link of the option titled ``text`` (ignoring case) in the field's picklist; "" when the field is a picklist but has no such option; None when it is not a picklist."""
        with self._lock:
            lookup = self._lookup_of(field_id)
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
            self._lookup_of(field_id)   # reads the fields once
            target = self._units.get(field_id, "")
        if not target:
            return None
        try:
            number = float(text.strip())
        except ValueError:
            return None
        converted = convert(number, unit, target)
        if converted is None:
            log.warning("Field %s is in %r, which %r does not convert to; sent as it is", field_id, target, unit)
            return None
        return f"{converted:.8g}", target

    def fit_number(self, field_id: str, text: str) -> str:
        """``text`` rounded to the decimal digits the field takes (unchanged when it is not a number or the field states no limit)."""
        with self._lock:
            self._lookup_of(field_id)   # reads the fields once
            digits = self._precisions.get(field_id)
        if digits is None:
            return text
        try:
            number = Decimal(text.strip())
        except InvalidOperation:
            return text
        if not number.is_finite():
            return text
        return format(number.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP).normalize(), "f")

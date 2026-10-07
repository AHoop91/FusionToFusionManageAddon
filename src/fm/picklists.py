"""Fits the text a property holds to the Fusion Manage field it is sent to.

A picklist or radio field takes a link to one of its lookup's options (``/api/v3/lookups/<name>/options/6``),
not the option's title, so a mapped text such as "Top Level Assembly" has to be found among the options first.
A number field refuses more decimal digits than its ``fieldPrecision``, so a number is rounded to fit.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import threading
from typing import Dict, List, Optional

from ..auth.errors import AuthError
from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmApiError, FmClient, last_segment
from .workspace import WorkspaceService

log = get_logger("fm.picklists")


class PicklistResolver:
    """The options of the picklist fields of one workspace, each read once (the resolver is shared by a run's threads)."""

    def __init__(self, client: FmClient, workspace_id: str) -> None:
        self._client = client
        self._workspace_id = workspace_id
        self._lock = threading.Lock()
        self._lookups: Optional[Dict[str, str]] = None   # field id -> lookup name
        self._precisions: Dict[str, int] = {}   # field id -> most decimal digits it takes
        self._options: Dict[str, List[Dict[str, str]]] = {}   # lookup name -> [{value: link, title}]

    def _lookup_of(self, field_id: str) -> str:
        """The lookup behind a fixed-list field ("" for any other field, or one that links to another workspace)."""
        if self._lookups is None:
            lookups: Dict[str, str] = {}
            try:
                data = self._client.get_json(f"{WORKSPACES}/{self._workspace_id}/fields")
            except (FmApiError, AuthError) as exc:
                log.warning("Could not read the fields of workspace %s: %s", self._workspace_id, exc)
                return ""   # not remembered, so the next field tries again
            rows = data.get("fields") if isinstance(data, dict) else data
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and isinstance(row.get("fieldPrecision"), int) and not isinstance(row["fieldPrecision"], bool):
                    self._precisions[last_segment(row.get("__self__"))] = row["fieldPrecision"]
                if isinstance(row, dict) and row.get("picklist") and not row.get("picklistFieldDefinition"):
                    lookups[last_segment(row.get("__self__"))] = last_segment(row["picklist"])
            self._lookups = lookups
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

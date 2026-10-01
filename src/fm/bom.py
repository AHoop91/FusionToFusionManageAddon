"""Read a Fusion Manage item's bill of materials.

The BOM comes from the workspace's default view as a bulk answer: ``nodes`` hold
the items and ``edges`` the parent/child lines, both naming items by urn. It is
reduced to ``{parent item number: [child lines]}`` for the BOM comparison.
"""

import re
import time
from datetime import date
from typing import Any, Dict, List

from ..core.logging_setup import get_logger
from .client import FmApiError, FmClient
from .items import FIELD_ID, display_text

log = get_logger("fm.bom")

QUANTITY_FIELDS = ("103", "293")   # quantity field ids seen in BOM views; others fall back to the first number
ATTEMPTS = 4          # reads of a BOM that comes back empty
RETRY_SECONDS = 1.5  # wait between them
ACCEPT = "*/*"   # the answer is application/vnd.autodesk.plm.bom.bulk+json
_REVISION = re.compile(r"\s*\[REV:[^\]]*\]\s*$")


def _name_of(title: str) -> str:
    """Name of a node title: after the item number, without the trailing ``[REV:x]``."""
    name = title.split(" - ", 1)[1] if " - " in title else ""
    return _REVISION.sub("", name).strip()


def _number_of(title: str) -> str:
    """Item number of a node title such as ``002772 - CASE ASSEMBLY V16 [REV:w]``."""
    return title.split(" - ", 1)[0].strip()


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _quantity(fields: List[Any]) -> str:
    """Quantity among an edge's fields: a known quantity field, else the first numeric value."""
    values = []
    for field in fields:
        if isinstance(field, dict):
            match = FIELD_ID.search(str((field.get("metaData") or {}).get("link", "")))
            values.append((match.group(1) if match else "", display_text(field.get("value"))))
    for field_id, text in values:
        if field_id in QUANTITY_FIELDS:
            return text
    return next((text for _, text in values if _is_number(text)), "")


def parse_bom(data: Any) -> Dict[str, List[Dict[str, str]]]:
    """``{parent item number: [{"number", "name", "quantity", "sequence"}]}`` from a bulk BOM answer.

    ``sequence`` is the line's BOM item number. The quantity is the edge field with
    one of ``QUANTITY_FIELDS`` as its id, else the first numeric edge field.
    """
    data = data if isinstance(data, dict) else {}
    titles = {str((n.get("item") or {}).get("urn", "")): str((n.get("item") or {}).get("title", ""))
              for n in data.get("nodes") or [] if isinstance(n, dict)}
    numbers = {urn: _number_of(title) for urn, title in titles.items()}
    children: Dict[str, List[Dict[str, str]]] = {number: [] for number in numbers.values() if number}
    for edge in data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        parent, child = numbers.get(str(edge.get("parent", ""))), numbers.get(str(edge.get("child", "")))
        if not parent or not child:
            continue
        children.setdefault(parent, []).append(
            {"number": child, "name": _name_of(titles[str(edge.get("child"))]),
             "quantity": _quantity(edge.get("fields") or []), "sequence": str(edge.get("itemNumber", ""))})
    return children


class BomService:
    """Reads BOMs of a workspace through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def read(self, workspace_id: str, item_id: str, depth: int) -> Dict[str, List[Dict[str, str]]]:
        """The item's BOM down to ``depth`` levels in the workspace's default view, by parent item number.

        ``effectiveDate`` is always sent: without it Fusion Manage sometimes answers 400 (``null wrong date format``).
        """
        path = (f"/api/v3/workspaces/{workspace_id}/items/{item_id}/bom"
                f"?depth={depth}&effectiveDate={date.today().isoformat()}&revisionBias=release&rootId={item_id}")
        # Right after start-up Fusion Manage can answer a BOM with no nodes at all, not even the root,
        # and give the full answer a moment later. An item always has itself as a node, so read again.
        for attempt in range(1, ATTEMPTS + 1):
            data = self._client.get_json(path, accept=ACCEPT)
            nodes = len(data.get("nodes") or []) if isinstance(data, dict) else 0
            log.info("BOM answer for %s: %d node(s), attempt %d", path, nodes, attempt)
            if nodes:
                return parse_bom(data)
            if attempt < ATTEMPTS:
                time.sleep(RETRY_SECONDS)
        raise FmApiError("Fusion Manage returned an empty Bill of Materials. Try again in a moment.")

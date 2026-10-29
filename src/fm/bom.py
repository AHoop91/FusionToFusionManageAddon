"""Read a Fusion Manage item's bill of materials.

The BOM comes from the workspace's default view as a bulk answer: ``nodes`` hold
the items and ``edges`` the parent/child lines, both naming items by urn. It is
reduced to ``{parent item number: [child lines]}`` for the BOM comparison.
"""

import re
from datetime import date
from typing import Any, Dict, List, Tuple

from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list, dict_rows, dig
from .client import WORKSPACES, FmApiError, FmClient
from .items import display_text
from .pages import field_id

log = get_logger("fm.bom")

QUANTITY_FIELDS = ("103", "293")   # quantity field ids seen in BOM views; others fall back to the first number
RELEASED_BIAS = "release"   # ``revisionBias``: the released revision of each line, or ...
WORKING_BIAS = "working"    # ... its working revision, which is where a line has to be changed or removed: a released one cannot be
ACCEPT = "application/vnd.autodesk.plm.bom.bulk+json"   # asked for by name: any other Accept can be answered with the tree form (item, fields ...) that has no nodes and edges
_REVISION = re.compile(r"\s*\[REV:[^\]]*\]\s*$")
_BOM_ITEM = re.compile(r"/bom-items/(\d+)")   # the id of a BOM line at the end of its link


def name_of(title: str) -> str:
    """Name of a node title: after the item number, without the trailing ``[REV:x]``."""
    name = title.split(" - ", 1)[1] if " - " in title else ""
    return _REVISION.sub("", name).strip()


def number_of(title: str) -> str:
    """Item number of a node title such as ``002772 - CASE ASSEMBLY V16 [REV:w]``."""
    return title.split(" - ", 1)[0].strip()


def split_title(title: str) -> Tuple[str, str]:
    """``("9410-306", "STEP")`` from a descriptor such as ``9410-306 - STEP [REV:w]``. With no " - " the number is "" and the name is
    the whole title (``number_of`` and ``name_of`` read the two parts separately)."""
    text = _REVISION.sub("", title).strip()
    number, dash, name = text.partition(" - ")
    return (number.strip(), name.strip()) if dash else ("", text)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _quantity(fields: Any) -> str:
    """Quantity among an edge's fields: a known quantity field, else the first numeric value."""
    values = []
    for field in dict_rows(fields):
        values.append((field_id(field.get("metaData")), display_text(field.get("value"))))
    for fid, text in values:
        if fid in QUANTITY_FIELDS:
            return text
    return next((text for _, text in values if _is_number(text)), "")


def _edge_id(edge: Dict[str, Any]) -> str:
    """Id of a BOM line (the ``13836`` of ``.../bom-items/13836``): ``edgeId``, else the end of ``edgeLink``; empty if neither is there."""
    if edge.get("edgeId"):
        return str(edge["edgeId"])
    match = _BOM_ITEM.search(str(edge.get("edgeLink") or edge.get("link") or ""))
    return match.group(1) if match else ""


def parse_bom(data: Any) -> Dict[str, List[Dict[str, str]]]:
    """``{parent item number: [{"number", "name", "quantity", "sequence", "edge_id"}]}`` from a bulk BOM answer.

    ``sequence`` is the line's BOM item number, ``edge_id`` the id Fusion Manage gives the line (to change or delete it). The quantity is the
    edge field with one of ``QUANTITY_FIELDS`` as its id, else the first numeric edge field. A line whose parent or child is not a node with
    an item number is left out.
    """
    data = as_dict(data)
    titles = {str(dig(n, "item", "urn") or ""): str(dig(n, "item", "title") or "") for n in dict_rows(data.get("nodes"))}
    numbers = {urn: number_of(title) for urn, title in titles.items()}
    children: Dict[str, List[Dict[str, str]]] = {number: [] for number in numbers.values() if number}
    for edge in dict_rows(data.get("edges")):
        parent_urn, child_urn = str(edge.get("parent") or ""), str(edge.get("child") or "")
        parent, child = numbers.get(parent_urn), numbers.get(child_urn)
        sequence = edge.get("itemNumber")   # 0 is a position
        if not parent or not child:
            continue
        children[parent].append({"number": child, "name": name_of(titles[child_urn]), "quantity": _quantity(edge.get("fields")),
                                 "sequence": "" if sequence is None else str(sequence), "edge_id": _edge_id(edge)})
    return children


class BomService:
    """Reads BOMs of a workspace through an ``FmClient``.

    ``bias`` is the revision of each line that is read (``RELEASED_BIAS``, the default, or ``WORKING_BIAS``). The ids of the lines belong to
    one revision of a parent, so a BOM read to change the working version has to be read with the working bias."""

    def __init__(self, client: FmClient, bias: str = RELEASED_BIAS) -> None:
        self._client, self._bias = client, bias

    def read(self, workspace_id: str, item_id: str, depth: int) -> Dict[str, List[Dict[str, str]]]:
        """The item's BOM down to ``depth`` levels in the workspace's default view, by parent item number.

        ``effectiveDate`` is always sent: without it Fusion Manage sometimes answers 400 (``null wrong date format``).
        """
        path = (f"{WORKSPACES}/{workspace_id}/items/{item_id}/bom"
                f"?depth={depth}&effectiveDate={date.today().isoformat()}&revisionBias={self._bias}&rootId={item_id}")
        data = self._client.get_json(path, accept=ACCEPT)
        nodes = len(as_list(dig(data, "nodes")))
        log.info("BOM answer for %s: %d node(s)", path, nodes)
        if not nodes:   # an item is always a node of its own BOM, so an answer with none is not a BOM
            raise FmApiError("Fusion Manage did not return the Bill of Materials (no nodes).")
        return parse_bom(data)

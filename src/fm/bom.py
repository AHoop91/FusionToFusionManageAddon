"""Read a Fusion Manage item's bill of materials.

The BOM comes from the workspace's default view as a bulk answer: ``nodes`` hold
the items and ``edges`` the parent/child lines, both naming items by urn. It is
reduced to ``{parent item number: [child lines]}`` for the BOM comparison.
"""

import re
from datetime import date
from typing import Any, Dict, List, Tuple

from ..core.logging_setup import get_logger
from ..core.i18n import t
from ..core.shapes import as_dict, as_list, dict_rows, dig
from .client import WORKSPACES, FmApiError, FmClient
from .components import link_ids, manage_link
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
    """``{parent item number: [{"number", "name", "quantity", "sequence", "edge_id", "item_id"}]}`` from a bulk BOM answer.

    ``sequence`` is the line's BOM item number, ``edge_id`` the id Fusion Manage gives the line (to change or delete it) and ``item_id`` the id
    of the item the line holds (the last part of the node's urn; empty when the urn is not an item's). The quantity is the
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
                                 "sequence": "" if sequence is None else str(sequence), "edge_id": _edge_id(edge), "item_id": link_ids(manage_link(child_urn, ""))[1]})
    return children


def _line_order(line: Dict[str, str]) -> int:
    """The sort key of a line: its BOM item number as a number, a line with none last."""
    text = str(line.get("sequence") or "").strip()
    return int(text) if text.isascii() and text.isdigit() else 10 ** 12


TREE_NODE_CAP = 20000   # lines of one tree: an item used in many places has its lines in each, so a tree can be far larger than the answer


def build_tree(lines: Dict[str, List[Dict[str, str]]], data: Any, root_id: str, depth: int, cap: int = TREE_NODE_CAP) -> Dict[str, Any]:
    """The tree of the item ``root_id`` from ``parse_bom``'s lines and the answer they came from. The lines of an item are those of its number, so an
    item in several places has them in each (a tree of more than ``cap`` lines raises). Only ``depth`` levels are made; a line at the last one whose
    own lines the answer shows elsewhere is marked ``cut`` (its lines were not read), not left to look empty. Raises ``FmApiError`` for an answer with
    no node for the item, a line (edge) whose parent or child has no item number, a line with no item id, or an item inside itself."""
    nodes = dict_rows(as_dict(data).get("nodes"))
    root = next((n for n in nodes if link_ids(manage_link(str(dig(n, "item", "urn") or ""), ""))[1] == root_id), None)
    if root is None:
        raise FmApiError(t("data.fm_bom_no_root"))
    numbers = {str(dig(n, "item", "urn") or ""): number_of(str(dig(n, "item", "title") or "")) for n in nodes}
    for edge in dict_rows(as_dict(data).get("edges")):   # parse_bom leaves such a line out: here that would be a tree with a hole in it
        if not numbers.get(str(edge.get("parent") or "")) or not numbers.get(str(edge.get("child") or "")):
            raise FmApiError(t("data.fm_bom_edge_no_number"))
    title = str(dig(root, "item", "title") or "")
    count = [0]

    def under(number: str, level: int, path: frozenset) -> List[Dict[str, Any]]:
        out = []
        for line in sorted(lines.get(number, []), key=_line_order):   # the BOM lists lines by their item number, not in the order the answer holds the edges
            if not line["item_id"]:
                raise FmApiError(t("data.fm_bom_line_no_item", number=line["number"]))
            if line["item_id"] in path:
                raise FmApiError(t("data.fm_bom_loop", number=line["number"]))
            count[0] += 1
            if count[0] > cap:
                raise FmApiError(t("data.fm_bom_too_big", count=cap))
            last = level + 1 >= depth
            node: Dict[str, Any] = {**line, "children": [] if last else under(line["number"], level + 1, path | {line["item_id"]})}
            if last and lines.get(line["number"]):
                node["cut"] = True
            out.append(node)
        return out

    return {"number": number_of(title), "name": name_of(title), "item_id": root_id, "children": under(number_of(title), 0, frozenset([root_id]))}


class BomService:
    """Reads BOMs of a workspace through an ``FmClient``.

    ``bias`` is the revision of each line that is read (``WORKING_BIAS``, the default, or ``RELEASED_BIAS``). The ids of the lines belong to
    one revision of a parent, so a BOM read to change or compare with the working version has to be read with the working bias."""

    def __init__(self, client: FmClient, bias: str = WORKING_BIAS) -> None:
        self._client, self._bias = client, bias

    def read(self, workspace_id: str, item_id: str, depth: int) -> Dict[str, List[Dict[str, str]]]:
        """The item's BOM down to ``depth`` levels in the workspace's default view, by parent item number.

        ``effectiveDate`` is always sent: without it Fusion Manage sometimes answers 400 (``null wrong date format``).
        """
        return parse_bom(self._answer(workspace_id, item_id, depth))

    def tree(self, workspace_id: str, item_id: str, depth: int) -> Dict[str, Any]:
        """The item's BOM down to ``depth`` levels as one tree: ``{"number", "name", "item_id", "children": [line]}``, each line with its
        ``number``, ``name``, ``quantity``, ``sequence``, ``edge_id``, ``item_id`` and ``children`` (the lines under it, in BOM order). Raises ``FmApiError`` when the
        answer has no node for the item, or a line has no item id."""
        data = self._answer(workspace_id, item_id, depth)
        return build_tree(parse_bom(data), data, item_id, depth)

    def _answer(self, workspace_id: str, item_id: str, depth: int) -> Any:
        path = (f"{WORKSPACES}/{workspace_id}/items/{item_id}/bom"
                f"?depth={depth}&effectiveDate={date.today().isoformat()}&revisionBias={self._bias}&rootId={item_id}")
        data = self._client.get_json(path, accept=ACCEPT)
        nodes = len(as_list(dig(data, "nodes")))
        log.info("BOM answer for %s: %d node(s)", path, nodes)
        if not nodes:   # an item is always a node of its own BOM, so an answer with none is not a BOM
            raise FmApiError(t("data.fm_no_bom_nodes"))
        return data

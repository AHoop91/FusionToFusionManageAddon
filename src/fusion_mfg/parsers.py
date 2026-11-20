"""Turn Manufacturing Data Model answers into plain dicts and lists.

The Data Model's GraphQL fields can be ``null`` (a component with no part number, a design with no thumbnail yet), so a missing or ``null``
branch reads as an empty value. A branch of the wrong type reads as empty too (see ``core.shapes``), rather than as an error.
"""

from typing import Any, Dict, List

from ..core.shapes import as_dict, as_list, dig
from ..core.i18n import t


def _model(data: Dict[str, Any]) -> Dict[str, Any]:
    """The first model in a ``bulkModels`` result."""
    models = dig(data, "bulkModels")
    return as_dict(dig(models[0], "model")) if isinstance(models, list) and models else {}


def _component(data: Dict[str, Any]) -> Dict[str, Any]:
    """The ``component`` of the first model in a ``bulkModels`` result."""
    return as_dict(_model(data).get("component"))


def _text(node: Any) -> str:
    """``{ value }`` wrapper to text."""
    if isinstance(node, dict):
        node = node.get("value")
    return "" if node is None else str(node)


def _id(node: Any) -> str:
    """The ``id`` of a node, as text."""
    return str(as_dict(node).get("id") or "")


def _item_number(component: Dict[str, Any]) -> str:
    """The item number of a component (its ``itemNumber { id }``)."""
    return _id(component.get("itemNumber"))


def parse_summary(data: Dict[str, Any]) -> Dict[str, str]:
    """The design's root component: its id and composition, item and part number, name and description, and the design's data file: its lineage
    id (``urn:adsk.wipprod:dm.lineage:...``) and its file name."""
    component = _component(data)
    design_item = as_dict(_model(data).get("designItem"))
    return {
        "lineage": _id(design_item),
        "file_name": str(design_item.get("name") or ""),
        "component_id": _id(component),
        "composition": str(component.get("composition") or ""),
        "item_number": _item_number(component),
        "part_number": _text(component.get("partNumber")),
        "name": _text(component.get("name")),
        "description": _text(component.get("description")),
    }


def _properties(node: Any) -> List[Dict[str, str]]:
    """Name/value rows of an ``allProperties`` node, by name; a row with no name is left out."""
    rows = as_dict(node).get("results")
    result = []
    for row in as_list(rows):
        if not isinstance(row, dict) or not row.get("name"):
            continue
        result.append({"name": str(row["name"]), "value": _text(row.get("displayValue"))})
    return sorted(result, key=lambda row: row["name"].lower())


def parse_properties(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """The properties of the first model's component in a ``bulkModels`` result."""
    return _properties(_component(data).get("allProperties"))


def parse_component(data: Dict[str, Any]) -> Dict[str, Any]:
    """A component's properties, from a query answer that has the ``component`` at its top: ``{"properties": [...]}``."""
    return {"properties": _properties(dig(data, "component", "allProperties"))}


def _sequence(relation: Dict[str, Any]) -> int:
    """The position of a relation among its siblings (0 when the Data Model gives none)."""
    return relation.get("sequenceNumber") or 0


def parse_structure(relations: List[Dict[str, Any]], root_id: str) -> List[Dict[str, Any]]:
    """Rebuild the BOM tree from flat relations, as rows in tree order with their ``level`` (0 = direct child).

    Raises ``ValueError`` when a component is found inside itself, which would never end."""
    children: Dict[str, List[Dict[str, Any]]] = {}
    for relation in relations:
        if isinstance(relation, dict) and isinstance(relation.get("toComponent"), dict):
            children.setdefault(_id(relation.get("fromComponent")), []).append(relation)

    result: List[Dict[str, Any]] = []

    def walk(parent: str, level: int, ancestors: frozenset) -> None:
        for relation in sorted(children.get(parent, []), key=_sequence):
            child = relation["toComponent"]
            child_id = _id(child)
            if child_id in ancestors:
                raise ValueError(t("data.mfg_bom_cycle", id=child.get("id")))
            item_number = _item_number(child)
            result.append({"level": level,
                           "id": child_id,
                           "has_children": bool(child.get("hasChildren")),   # so an assembly shows its chevron before its lines are read
                           "item_number": item_number,
                           "sequence": _sequence(relation),
                           "name": _text(child.get("name")),
                           "part_number": _text(child.get("partNumber")) or item_number,
                           "description": _text(child.get("description")),
                           "quantity": str(as_dict(relation.get("quantityProperty")).get("displayValue") or "")})
            walk(child_id, level + 1, ancestors | {child_id})

    walk(root_id, 0, frozenset([root_id]))
    return result

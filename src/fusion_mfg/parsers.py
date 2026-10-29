"""Turn Manufacturing Data Model answers into plain dicts and lists.

Parsing is defensive: a missing, ``null`` or wrongly shaped branch yields an empty value rather than an error.
"""

from typing import Any, Dict, List

from ..core.shapes import as_dict, as_list, dig


def _component(data: Dict[str, Any]) -> Dict[str, Any]:
    """The ``component`` of the first model in a ``bulkModels`` result."""
    models = dig(data, "bulkModels")
    return as_dict(dig(models[0], "model", "component")) if isinstance(models, list) and models else {}


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
    """The design's root component: its id and composition, item and part number, name and description."""
    component = _component(data)
    return {
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


def parse_structure(relations: List[Dict[str, Any]], root_id: str) -> List[Dict[str, Any]]:
    """Rebuild the BOM tree from flat relations, as rows in tree order with their ``level`` (0 = direct child).

    Raises ``ValueError`` when a component is found inside itself, which would never end."""
    children: Dict[str, List[Dict[str, Any]]] = {}
    for relation in relations:
        if isinstance(relation, dict) and isinstance(relation.get("toComponent"), dict):
            children.setdefault(_id(relation.get("fromComponent")), []).append(relation)

    result: List[Dict[str, Any]] = []

    def walk(parent: str, level: int, ancestors: frozenset) -> None:
        for relation in sorted(children.get(parent, []), key=lambda r: r.get("sequenceNumber") or 0):
            child = relation["toComponent"]
            child_id = _id(child)
            if child_id in ancestors:
                raise ValueError(f"The Bill of Materials contains a component inside itself ({child.get('id')}).")
            item_number = _item_number(child)
            result.append({"level": level,
                           "id": child_id,
                           "has_children": bool(child.get("hasChildren")),   # so an assembly shows its chevron before its lines are read
                           "item_number": item_number,
                           "sequence": relation.get("sequenceNumber") or 0,
                           "name": _text(child.get("name")),
                           "part_number": _text(child.get("partNumber")) or item_number,
                           "description": _text(child.get("description")),
                           "quantity": str(as_dict(relation.get("quantityProperty")).get("displayValue") or "")})
            walk(child_id, level + 1, ancestors | {child_id})

    walk(root_id, 0, frozenset([root_id]))
    return result

"""Turn ``bulkModels`` answers into plain dicts and lists.

Parsing is defensive: missing or ``null`` branches yield empty values rather
than errors.
"""

from typing import Any, Dict, List


def _component(data: Dict[str, Any]) -> Dict[str, Any]:
    """The ``component`` of the first model in a ``bulkModels`` result."""
    models = data.get("bulkModels") or []
    first = models[0] if models and isinstance(models[0], dict) else {}
    model = first.get("model") or {}
    return model.get("component") or {}


def _text(node: Any) -> str:
    """``{ value }`` wrapper to text."""
    if isinstance(node, dict):
        node = node.get("value")
    return "" if node is None else str(node)


def parse_summary(data: Dict[str, Any]) -> Dict[str, str]:
    component = _component(data)
    thumb = component.get("thumbnail") or {}
    return {
        "component_id": str(component.get("id") or ""),
        "composition": str(component.get("composition") or ""),
        "item_number": str((component.get("itemNumber") or {}).get("id") or ""),
        "part_number": _text(component.get("partNumber")),
        "description": _text(component.get("description")),
        "thumbnail": str(thumb.get("signedUrl") or ""),
    }


def _properties(node: Any) -> List[Dict[str, str]]:
    """Sorted name/value rows of an ``allProperties`` node."""
    rows = ((node or {}).get("results")) or []
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        shown = row.get("displayValue")
        result.append({"name": str(row["name"]), "value": "" if shown is None else str(shown)})
    return sorted(result, key=lambda r: r["name"].lower())


def parse_properties(data: Dict[str, Any]) -> List[Dict[str, str]]:
    return _properties(_component(data).get("allProperties"))


def parse_component(data: Dict[str, Any]) -> Dict[str, Any]:
    """A component's properties and the drawings of its primary model."""
    component = data.get("component") or {}
    model = component.get("primaryModel") or {}
    drawings = []
    for row in ((model.get("drawings") or {}).get("results")) or []:
        if not isinstance(row, dict):
            continue
        files = [{"format": str(d.get("outputFormat") or ""), "status": str(d.get("status") or ""),
                  "url": str(d.get("signedUrl") or "")}
                 for d in row.get("derivatives") or [] if isinstance(d, dict)]
        drawings.append({"id": str(row.get("id") or ""), "name": str(row.get("name") or ""),
                         "item_number": str((row.get("itemNumber") or {}).get("id") or ""), "files": files})
    return {"properties": _properties(component.get("allProperties")), "drawings": drawings}


def parse_structure(relations: List[Dict[str, Any]], root_id: str) -> List[Dict[str, Any]]:
    """Rebuild the BOM tree from flat relations, as rows in tree order with their ``level`` (0 = direct child)."""
    children: Dict[str, List[Dict[str, Any]]] = {}
    for row in relations:
        if isinstance(row, dict) and isinstance(row.get("toComponent"), dict):
            parent = str((row.get("fromComponent") or {}).get("id") or "")
            children.setdefault(parent, []).append(row)

    result: List[Dict[str, Any]] = []

    def walk(parent: str, level: int) -> None:
        if level > 20:   # guard against a cyclic answer
            return
        for row in sorted(children.get(parent, []), key=lambda r: r.get("sequenceNumber") or 0):
            child = row["toComponent"]
            result.append({"level": level,
                           "id": str(child.get("id") or ""),
                           "item_number": str((child.get("itemNumber") or {}).get("id") or ""),
                           "sequence": row.get("sequenceNumber") or 0,
                           "name": _text(child.get("name")),
                           "part_number": _text(child.get("partNumber")) or str((child.get("itemNumber") or {}).get("id") or ""),
                           "description": _text(child.get("description")),
                           "thumbnail": str((child.get("thumbnail") or {}).get("signedUrl") or ""),
                           "quantity": str((row.get("quantityProperty") or {}).get("displayValue") or "")})
            walk(str(child.get("id") or ""), level + 1)

    walk(root_id, 0)
    return result

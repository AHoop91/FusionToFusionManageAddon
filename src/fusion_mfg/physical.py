"""The physical properties of a component: mass, volume, area, density and the bounding box.

They are not in ``allProperties``; the Data Model works them out from the geometry (``status`` says when they
are ready), so they are read next to a component's properties and added to its property rows as
"Physical Mass", "Physical Length" and so on (the names a ``physical:<name>`` mapping source reads).
"""

from typing import Any, Dict, List

from ..config.workspace_models import PHYSICAL_NAMES
from ..core.logging_setup import get_logger

log = get_logger("physical")

_PHYSICAL = """physicalProperties {
        status
        area { value displayValue definition { units { name } } }
        volume { value displayValue definition { units { name } } }
        mass { value displayValue definition { units { name } } }
        density { value displayValue definition { units { name } } }
        boundingBox {
          length { value displayValue definition { units { name } } }
          height { value displayValue definition { units { name } } }
          width { value displayValue definition { units { name } } }
        }
      }"""

# A component's properties and its physical properties, which belong to its primary model, in one request.
COMPONENT_WITH_PHYSICAL_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    allProperties(pagination: { limit: 500 }) {
      results { name displayValue }
    }
    primaryModel { %s }
  }
}
""" % _PHYSICAL

READY = "COMPLETED"


# Fusion Manage's weight field is in kilograms; the Data Model gives the mass in whatever unit it names (grams in a metric design).
KILOGRAMS_PER = {"kilograms": 1.0, "kilogram": 1.0, "kg": 1.0, "grams": 0.001, "gram": 0.001, "g": 0.001, "milligrams": 1e-6, "milligram": 1e-6, "mg": 1e-6,
                 "pounds": 0.45359237, "pound": 0.45359237, "lbs": 0.45359237, "lb": 0.45359237, "ounces": 0.028349523125, "ounce": 0.028349523125, "oz": 0.028349523125}


def _unit(node: Dict[str, Any]) -> str:
    """The unit a property's value is in: the one its definition names, else the word after the number of its display value."""
    named = (((node.get("definition") or {}).get("units")) or {}).get("name")
    if named:
        return str(named).strip().lower()
    parts = str(node.get("displayValue") or "").split()
    return parts[-1].strip("[]()").lower() if len(parts) > 1 else ""


def _number(node: Any, kilograms: bool = False) -> str:
    """A property's value as plain text: the number itself (no units, which a Fusion Manage number field refuses), else its display value.

    ``kilograms`` converts a mass to kilograms whatever unit the Data Model gave it in.
    """
    if not isinstance(node, dict):
        return ""
    value = node.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if kilograms:
            factor = KILOGRAMS_PER.get(_unit(node))
            if factor is None:
                log.warning("Mass is in an unknown unit %r (value %s, shown as %r); sent as it is", _unit(node), value, node.get("displayValue"))
            else:
                value = value * factor
        return f"{value:.6g}"
    shown = node.get("displayValue")
    return "" if shown is None else str(shown)


def parse_physical(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Property rows (``Physical <name>``) from a ``COMPONENT_WITH_PHYSICAL_QUERY`` answer; none until the Data Model has them ready."""
    node = (((data.get("component") or {}).get("primaryModel") or {}).get("physicalProperties")) or {}
    if node.get("status") != READY:
        return []
    box = node.get("boundingBox") or {}
    found = {"Mass": node.get("mass"), "Volume": node.get("volume"), "Area": node.get("area"), "Density": node.get("density"),
             "Length": box.get("length"), "Width": box.get("width"), "Height": box.get("height")}
    log.debug("Physical properties as the Data Model gave them: %s", found)
    return [{"name": "Physical " + name, "value": _number(found[name], kilograms=name == "Mass")} for name in PHYSICAL_NAMES]

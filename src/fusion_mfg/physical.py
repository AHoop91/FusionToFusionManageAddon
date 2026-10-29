"""The physical properties of a component: mass, volume, area, density and the bounding box.

They are not in ``allProperties``; the Data Model works them out from the geometry (``status`` says when they are ready), so they are read
next to a component's properties and added to its property rows as "Physical Mass", "Physical Length" and so on (the names a
``physical:<name>`` mapping source reads).
"""

from typing import Any, Dict, List

from ..config.workspace_models import PHYSICAL_NAMES
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, dig

log = get_logger("physical")

READY = "COMPLETED"   # the ``status`` of physical properties the Data Model has worked out

_MEASURE = "{ value displayValue definition { units { name } } }"   # a measurement: its number, how it is shown and its unit

_PHYSICAL = """physicalProperties {
        status
        area %(m)s
        volume %(m)s
        mass %(m)s
        density %(m)s
        boundingBox {
          length %(m)s
          height %(m)s
          width %(m)s
        }
      }""" % {"m": _MEASURE}

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

# The physical properties as the fields of a component, to add to a query (see ``model_service.publish_query``).
PHYSICAL_FIELDS = "primaryModel { %s }" % _PHYSICAL

# Fusion Manage's weight field is in kilograms; the Data Model gives the mass in whatever unit it names (grams in a metric design). A unit is
# looked up in the singular, so "grams" and "lbs" are found as "gram" and "lb".
KILOGRAMS_PER = {"kilogram": 1.0, "kg": 1.0, "gram": 0.001, "g": 0.001, "milligram": 1e-6, "mg": 1e-6,
                 "pound": 0.45359237, "lb": 0.45359237, "ounce": 0.028349523125, "oz": 0.028349523125}

_SHORT = {"kilogram": "kg", "gram": "g", "milligram": "mg", "pound": "lb", "ounce": "oz", "millimeter": "mm", "centimeter": "cm",
          "meter": "m", "inch": "in", "foot": "ft"}
_POWERS = {"square": "²", "cubic": "³"}


def _unit(node: Dict[str, Any]) -> str:
    """The unit a property's value is in: the one its definition names, else the word after the number of its display value."""
    named = dig(node, "definition", "units", "name")
    if named:
        return str(named).strip().lower()
    parts = str(node.get("displayValue") or "").split()
    return parts[-1].strip("[]()").lower() if len(parts) > 1 else ""


def _symbol(unit: str) -> str:
    """A unit's short form for display: "kilograms per cubic centimeter" is "kg/cm³" (a unit it does not know is shown as it is)."""
    text = unit.strip().lower().replace("^2", "²").replace("^3", "³")
    top, per, bottom = text.partition(" per ")
    if per:
        return f"{_symbol(top)}/{_symbol(bottom)}"
    word, _, rest = text.partition(" ")
    if word in _POWERS and rest:
        return _symbol(rest) + _POWERS[word]
    base = text.rstrip("²³")
    return _SHORT.get(base.rstrip("s"), base) + text[len(base):]


def _number(node: Any, kilograms: bool = False) -> Dict[str, str]:
    """A property's ``value`` as plain text: the number itself (no units, which a Fusion Manage number field refuses), else its display value.

    ``unit`` is the unit of that value and ``original`` the number as the Data Model gave it, with its own unit.
    ``kilograms`` converts a mass to kilograms whatever unit the Data Model gave it in.
    """
    if not isinstance(node, dict):
        return {"value": "", "unit": "", "original": ""}
    value = node.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        unit_name = _unit(node)
        unit = _symbol(unit_name)
        original = f"{value:.10g} {unit}".strip()
        if kilograms:
            factor = KILOGRAMS_PER.get(unit_name.rstrip("s"))
            if factor is None:
                log.warning("Mass is in an unknown unit %r (value %s, shown as %r); sent as it is", unit_name, value, node.get("displayValue"))
            else:
                value, unit = value * factor, "kg"
        return {"value": f"{value:.6g}", "unit": unit, "original": original}
    shown = node.get("displayValue")
    text = "" if shown is None else str(shown)
    return {"value": text, "unit": "", "original": text}


def parse_physical(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Property rows (``Physical <name>``, with its ``unit`` and ``original`` value) from a ``COMPONENT_WITH_PHYSICAL_QUERY`` answer.

    None until the Data Model has them ready."""
    node = as_dict(dig(data, "component", "primaryModel", "physicalProperties"))
    if node.get("status") != READY:
        return []
    box = as_dict(node.get("boundingBox"))
    found = {"Mass": node.get("mass"), "Volume": node.get("volume"), "Area": node.get("area"), "Density": node.get("density"),
             "Length": box.get("length"), "Width": box.get("width"), "Height": box.get("height")}
    log.debug("Physical properties as the Data Model gave them: %s", found)
    return [{"name": "Physical " + name, **_number(found.get(name), kilograms=name == "Mass")} for name in PHYSICAL_NAMES]

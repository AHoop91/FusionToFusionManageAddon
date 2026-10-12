"""Convert a number between units of length, mass and their powers (area, volume, density).

The Data Model gives a physical property in Fusion's own units (centimetres, kilograms) while a Fusion Manage field holds
the unit its workspace set (millimetres, say). Units are read from their symbol (``cm³``, ``kg/cm³``) or name (``Cubic
centimeters``, ``kilograms per cubic centimeter``), and only units of the same dimension convert.
"""

from typing import Dict, Optional, Tuple

Unit = Tuple[Tuple[int, int], float]   # (powers of length and of mass, size in metres and kilograms)

_ATOMS: Dict[str, Unit] = {}


def _add(names: str, dims: Tuple[int, int], size: float) -> None:
    for name in names.split():
        _ATOMS[name] = (dims, size)


_add("mm millimeter millimeters millimetre millimetres", (1, 0), 0.001)
_add("cm centimeter centimeters centimetre centimetres", (1, 0), 0.01)
_add("m meter meters metre metres", (1, 0), 1.0)
_add("in inch inches", (1, 0), 0.0254)
_add("ft foot feet", (1, 0), 0.3048)
_add("kg kilogram kilograms", (0, 1), 1.0)
_add("g gram grams", (0, 1), 0.001)
_add("mg milligram milligrams", (0, 1), 1e-6)
_add("lb lbs pound pounds", (0, 1), 0.45359237)
_add("oz ounce ounces", (0, 1), 0.028349523125)

_POWERS = {"square": 2, "cubic": 3}
_SUPERSCRIPT = {"²": 2, "³": 3}


def _power(unit: Unit, power: int) -> Unit:
    (length, mass), size = unit
    return (length * power, mass * power), size ** power


def _parse(text: str) -> Optional[Unit]:
    text = " ".join(text.strip().lower().replace("^2", "²").replace("^3", "³").split())
    for divider in (" per ", "/"):
        top, found, bottom = text.partition(divider)
        if found:
            a, b = _parse(top), _parse(bottom)
            return None if a is None or b is None else ((a[0][0] - b[0][0], a[0][1] - b[0][1]), a[1] / b[1])
    word, _, rest = text.partition(" ")
    if word in _POWERS and rest:
        base = _parse(rest)
        return None if base is None else _power(base, _POWERS[word])
    if text and text[-1] in _SUPERSCRIPT:
        base = _parse(text[:-1])
        return None if base is None else _power(base, _SUPERSCRIPT[text[-1]])
    return _ATOMS.get(text)


def convert(value: float, source: str, target: str) -> Optional[float]:
    """``value`` given in ``source`` units, in ``target`` units; None when either unit is not known or they measure different things."""
    a, b = _parse(source), _parse(target)
    if a is None or b is None or a[0] != b[0]:
        return None
    return value * a[1] / b[1]

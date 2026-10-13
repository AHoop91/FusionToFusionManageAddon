"""What the Export window offers: the formats of the open document, and where a file can go.

Fusion's own exporters have no settings worth offering (the STEP protocol, for one, is Fusion's to choose), so a format is just a name.
This holds no Fusion objects: the page shows what ``describe`` says.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

STEP, PDF, DWG, DXF = "step", "pdf", "dwg", "dxf"
ITEM, COMPONENT = "item", "component"   # where the file is attached in Fusion Manage: the item of the part, or its component

DESIGN, DRAWING = "design", "drawing"   # the kinds of open document that can be exported
FORMATS_OF = {DESIGN: (STEP,), DRAWING: (PDF, DWG, DXF)}   # the first is the one offered at first


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    extension: str


FORMATS: Dict[str, Format] = {
    STEP: Format(STEP, "STEP", ".step"),
    PDF: Format(PDF, "PDF", ".pdf"),
    DWG: Format(DWG, "DWG", ".dwg"),
    DXF: Format(DXF, "DXF", ".dxf"),
}


def formats_for(document: str) -> List[str]:
    """The format keys the open ``document`` ("design" or "drawing"; anything else has none) can be exported as."""
    return list(FORMATS_OF.get(document, ()))


def describe(key: str) -> Dict[str, Any]:
    """The format ``key`` as the page shows it."""
    found = FORMATS[key]
    return {"key": found.key, "label": found.label, "ext": found.extension}

"""Where each kind of exported file is attached in Fusion Manage: to the item of the part, or to its component."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..core.shapes import as_dict, dig

STEP, PDF, DWG, DXF = "step", "pdf", "dwg", "dxf"
ITEM, COMPONENT = "item", "component"

EXPORT_FORMATS = (STEP, PDF, DWG, DXF)   # in the order the Export tab lists them
DESTINATIONS = (ITEM, COMPONENT)
DEFAULT_DESTINATION = ITEM


@dataclass
class ExportSettings:
    """For each file format, the destination its Export window choice starts on."""

    destinations: Dict[str, str] = field(default_factory=lambda: {key: DEFAULT_DESTINATION for key in EXPORT_FORMATS})

    def destination_of(self, key: str) -> str:
        """The destination set for format ``key`` (the default one when it has none)."""
        return self.destinations.get(key, DEFAULT_DESTINATION)

    def validate(self) -> List[str]:
        return [f"{key.upper()} must go to the item or the component." for key in EXPORT_FORMATS if self.destination_of(key) not in DESTINATIONS]

    def to_dict(self) -> Dict[str, Any]:
        return {"destinations": {key: self.destination_of(key) for key in EXPORT_FORMATS}}

    @classmethod
    def from_dict(cls, data: Any) -> "ExportSettings":
        """Build from stored JSON, ignoring unknown formats and bad destinations."""
        stored = as_dict(dig(data, "destinations"))
        return cls({key: stored[key] if stored.get(key) in DESTINATIONS else DEFAULT_DESTINATION for key in EXPORT_FORMATS})

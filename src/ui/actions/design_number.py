"""The item number of the design open in Fusion, for the actions that assign it."""

from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:   # only for the types: importing these loads Fusion's modules
    from ..item_numbers import DesignRef, ItemNumbers


class OpenDesign:
    """Reads which design is open (on Fusion's UI thread) and its item number (on a worker). Fusion's modules are loaded when first asked, so
    what imports this runs without Fusion."""

    def __init__(self) -> None:
        self._numbers: Optional["ItemNumbers"] = None

    def ref(self) -> "DesignRef":
        """The reference of the open design. UI thread."""
        from ..item_numbers import active_design_ref
        return active_design_ref()

    def number(self, ref: "DesignRef") -> str:
        """The item number of the design (what Fusion Manage finds its component by). Raises ``NoItemNumber`` with the reason when it has none."""
        return self._item_numbers().resolve(ref, "").item_number

    def describe(self, ref: "DesignRef") -> Dict[str, str]:
        """``{"number", "name", "thumbnail_url"}`` of the design (see ``ItemNumbers.describe``). Raises ``NoItemNumber`` when it is not saved."""
        return self._item_numbers().describe(ref)

    def record_link(self, ref: "DesignRef") -> str:
        """The API link of the design's record in the Components workspace ("" when it has none; see ``ItemNumbers.record_link``)."""
        return self._item_numbers().record_link(ref, "")

    def _item_numbers(self) -> "ItemNumbers":
        """The item numbers, made when first asked (they load Fusion's modules)."""
        if self._numbers is None:
            from ..item_numbers import ItemNumbers
            self._numbers = ItemNumbers()
        return self._numbers

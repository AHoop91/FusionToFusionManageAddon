"""The item number of the design open in Fusion, for the actions that assign it."""

from typing import Any, Optional


class OpenDesign:
    """Reads which design is open (on Fusion's UI thread) and its item number (on a worker). Fusion's modules are loaded when first asked, so
    what imports this runs without Fusion."""

    def __init__(self) -> None:
        self._numbers: Optional[Any] = None

    def ref(self) -> Any:
        """The reference of the open design. UI thread."""
        from ..item_numbers import active_design_ref
        return active_design_ref()

    def number(self, ref: Any) -> str:
        """The item number of the design (what Fusion Manage finds its component by). Raises ``NoItemNumber`` with the reason when it has none."""
        return self._item_numbers().resolve(ref, "").item_number

    def _item_numbers(self) -> Any:
        if self._numbers is None:
            from ..item_numbers import ItemNumbers
            self._numbers = ItemNumbers()
        return self._numbers

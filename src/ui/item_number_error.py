"""The refusal of a design or component that has no item number, apart from ``item_numbers`` so what only catches it runs without Fusion."""


class NoItemNumber(Exception):
    """The component has no item number in the Data Model (or it cannot be told which), so it is not published."""

"""What is selected or open in Fusion, and which Data Model reference it has.

This holds the reads of Fusion's own objects that the Item panel, the right-click menu and the Export window share: the component an entity
of the selection belongs to, the part number of the selection or of the open design (or of the design a drawing shows), the Data Model
reference of that part, and what Export would export. It also keeps the selection the right-click menu saw when it last opened.

Layer: UI (Fusion-facing reads, beside ``drawing_source``). It reads Fusion's objects only: no Fusion Manage, no worker threads and no
panel state. Every function that reads Fusion runs on the UI thread.
"""

from typing import Any, List, Optional, Tuple

import adsk.core
import adsk.fusion

from . import drawing_source
from .item_numbers import DesignRef, active_design_ref, component_ref, design_ref

menu_selection: List[Any] = []   # what was selected when the right-click menu last opened: choosing an entry may have cleared the selection by then


def component_of(entity: Any) -> Optional[adsk.fusion.Component]:
    """The component an entity of the selection belongs to: the component or occurrence itself, else the one holding the body, face, sketch or feature."""
    try:
        occurrence = adsk.fusion.Occurrence.cast(entity)
        if occurrence is not None:
            return occurrence.component
        component = adsk.fusion.Component.cast(entity)
    except (TypeError, RuntimeError):   # an object this API has no type for, such as the top of a drawing's tree
        return None
    if component is not None:
        return component
    for hop in (lambda e: e.assemblyContext.component if e.assemblyContext else None,   # a body or face seen through an occurrence
                lambda e: e.parentComponent,                                          # a body, sketch, feature or joint
                lambda e: e.body.parentComponent):                                    # a face, edge or vertex
        try:
            found = hop(entity)
        except (AttributeError, RuntimeError):
            continue
        if found is not None:
            return found
    return None


def selected_component_number(entities: Any) -> str:
    """Part number of the first component the entities belong to ("" when none does, or it has no number)."""
    for entity in entities:
        component = component_of(entity)
        if component is not None:
            return str(component.partNumber or "").strip()
    return ""


def active_selection() -> List[Any]:
    """The entities selected now. UI thread."""
    selections = adsk.core.Application.get().userInterface.activeSelections
    return [selections.item(index).entity for index in range(selections.count)]


def selected_part_number(from_menu: bool = False) -> str:
    """Part number of the selected component, else of the open design ("" if neither has one). In a drawing the same: a component
    of the tree gives its own number, and the top of the tree (or nothing) the number of the design the drawing shows, which is
    "" until that has loaded. ``from_menu`` reads what was selected when the right-click menu opened. Runs on the UI thread."""
    number = selected_component_number(menu_selection if from_menu else active_selection())
    if number:
        return number
    if drawing_source.active_drawing() is not None:
        return drawing_source.top_level_number()[0]
    design = open_design()
    return str(design.rootComponent.partNumber or "").strip() if design is not None else ""


def _own_ref(part_number: str) -> Optional[DesignRef]:
    """The reference of the Data Model's own model of the selected component that has ``part_number`` (see ``component_ref``), or None when
    the selection holds no such component or it has none. UI thread."""
    if drawing_source.active_drawing() is not None:
        return None
    design = open_design()
    for entity in active_selection():
        component = component_of(entity)
        if component is not None and str(component.partNumber or "").strip() == part_number:
            return component_ref(component, design)
    return None


def open_design() -> Optional[adsk.fusion.Design]:
    """The design open in Fusion, or None when the open document is not a design (a drawing, or none). UI thread."""
    return adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)


def active_ref() -> DesignRef:
    """The Data Model reference of the open design, or of the design the open drawing shows. UI thread."""
    if drawing_source.active_drawing() is not None:
        return design_ref(drawing_source.referenced_design())
    return active_design_ref()


def part_ref(part_number: str) -> DesignRef:
    """Where the Data Model finds the component with ``part_number``: its own model when it is selected and has one, else the open design
    (or the design the open drawing shows). UI thread."""
    return _own_ref(part_number) or active_ref()


def _root_of(design: Optional[adsk.fusion.Design]) -> Optional[adsk.fusion.Component]:
    """The top component of ``design``, or None when there is no design."""
    return design.rootComponent if design is not None else None


def export_component() -> Tuple[Optional[adsk.fusion.Component], Optional[adsk.fusion.Design]]:
    """``(component, design)`` Export exports: the selected component of the open design (else its top), or the top of the design a drawing
    shows. Either is None when there is none. UI thread."""
    if drawing_source.active_drawing() is not None:
        design = drawing_source.referenced_design()
        return _root_of(design), design
    selected = next((c for c in map(component_of, active_selection()) if c is not None), None)
    design = open_design()
    return selected or _root_of(design), design


def selects_root(entities: Any) -> bool:
    """Whether the root component of the open design is among the selected entities."""
    design = open_design()
    if design is None:
        return False
    root = design.rootComponent.entityToken
    for entity in entities:
        component = adsk.fusion.Component.cast(entity)   # the component itself, not a body or occurrence inside it
        if component is not None and component.entityToken == root:
            return True
    return False

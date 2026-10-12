"""The kinds of file the add-in attaches to a Fusion Manage item: a STEP file of a design, and a PDF of a drawing."""

from typing import Any, Iterable, List, Optional

import adsk.core
import adsk.fusion

from ..core.constants import ITEM_COMMAND_NAME
from ..publish.exporters import catch_up, export_step
from . import drawing_source
from .attachment_upload import Progress, UploadJob
from .item_numbers import Subject


SCAN_CATCH_UP = 5   # occurrences read between two times Fusion is let draw
_picked: List[Any] = []   # the occurrence the user selected, so a component is not searched for among every occurrence of the design


def pick(entities: Iterable[Any]) -> None:
    """Remember the occurrence among the selected ``entities`` (or the one a selected body or face is seen through). UI thread."""
    _picked.clear()
    for entity in entities:
        try:
            occurrence = adsk.fusion.Occurrence.cast(entity) or getattr(entity, "assemblyContext", None)
        except (TypeError, RuntimeError):   # an object this API has no type for
            continue
        if occurrence is not None:
            _picked.append(occurrence)
            return


def _component_of_number(design: adsk.fusion.Design, number: str, progress: Progress) -> Optional[Any]:
    """The occurrence in ``design`` of the component with part number ``number``: the one picked when it is that, else the first
    found by reading the part number of every occurrence, which is slow (None when there is none). That is done in view of the
    progress: Fusion is let draw, and answer the page's poll, every few reads."""
    for occurrence in _picked:
        try:
            if str(occurrence.component.partNumber or "").strip() == number:
                return occurrence
        except RuntimeError:   # it is gone
            pass
    seen = set()   # an occurrence of a component already read says nothing new
    occurrences = design.rootComponent.allOccurrences
    for index, occurrence in enumerate(occurrences):
        if index % SCAN_CATCH_UP == 0:
            progress(index * 100 // occurrences.count)
            catch_up()
        component = occurrence.component
        if component.id in seen:
            continue
        seen.add(component.id)
        if str(component.partNumber or "").strip() == number:
            return occurrence
    return None


def _export_design(path: str, subject: Subject, progress: Progress) -> None:
    """Write a STEP file of the item ``subject``: the whole design when that is its top-level component, else the component below it."""
    number = subject.part_number
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if str(design.rootComponent.partNumber or "").strip() == number:
        export_step(path)
        return
    occurrence = _component_of_number(design, number, progress)
    if occurrence is None:
        raise LookupError(f"No component with part number {number} in the open design.")
    progress(None)   # one call that cannot be followed
    export_step(path, [occurrence], part_number=number)


def _confirm_design(ui: adsk.core.UserInterface, subject: Subject) -> bool:
    """Whether a design is open to make the STEP file of item ``subject`` from. Whether it holds that item is found out when the file
    is made: looking for it here would hold up the click, on Fusion's UI thread."""
    if adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is None:
        ui.messageBox("Open the design to publish as a STEP file first.", ITEM_COMMAND_NAME)
        return False
    return True


def _confirm_drawing(ui: adsk.core.UserInterface, subject: Subject) -> bool:
    """Whether the open drawing may be attached as the PDF of item ``subject``: it is a drawing of that item, or the user says so."""
    held, reason = drawing_source.top_level_number()
    if not held:
        ui.messageBox(f"The drawing is not ready yet:\n{reason}", ITEM_COMMAND_NAME)
        return False
    if held == subject.part_number:
        return True
    question = (f"The open drawing is of {held}, but the item is {subject.item_number} ({subject.part_number}).\n\n"
                f"Upload this drawing as {subject.item_number}.pdf anyway?")
    return ui.messageBox(question, ITEM_COMMAND_NAME, adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes


STEP_JOB = UploadJob("Uploading STEP File", "STEP file", ".step", ("Find item", "Create STEP", "Upload"), _export_design, _confirm_design)
DRAWING_JOB = UploadJob("Uploading Drawing Representation", "drawing PDF", ".pdf", ("Find item", "Create PDF", "Upload"), lambda path, _subject, _progress: drawing_source.export_pdf(path), _confirm_drawing)

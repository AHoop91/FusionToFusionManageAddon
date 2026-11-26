"""The kinds of file the add-in attaches to a Fusion Manage item: a STEP file of a design, and a PDF, DWG or DXF of a drawing (UI layer: it reads Fusion's open document and asks the user to confirm)."""

from typing import Any, Callable, Iterable, List, Optional

import adsk.core
import adsk.fusion

from ..core.i18n import t
from ..publish.exporters import catch_up, export_step
from . import drawing_source
from .attachment_upload import Progress, UploadJob
from .export_options import DWG, DXF, PDF, STEP
from .item_numbers import Subject
from .ui_text import item_command_name


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
        raise LookupError(t("app.no_component_in_design", number=number))
    progress(None)   # one call that cannot be followed
    export_step(path, occurrence)


def _confirm_design(ui: adsk.core.UserInterface, subject: Subject) -> bool:
    """Whether a design is open to make the STEP file of item ``subject`` from. Whether it holds that item is found out when the file
    is made: looking for it here would hold up the click, on Fusion's UI thread."""
    if adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) is None:
        ui.messageBox(t("app.open_design_for_step"), item_command_name())
        return False
    return True


def _confirm_drawing(extension: str) -> Callable[[adsk.core.UserInterface, Subject], bool]:
    """A check of whether the open drawing may be attached as the ``extension`` file of item ``subject``: it is a drawing of that item, or the user says so."""
    def confirm(ui: adsk.core.UserInterface, subject: Subject) -> bool:
        held, reason = drawing_source.top_level_number()
        if not held:
            ui.messageBox(t("app.drawing_not_ready_box", reason=reason), item_command_name())
            return False
        if held == subject.part_number:
            return True
        question = t("app.confirm_other_drawing", held=held, item_number=subject.item_number, part_number=subject.part_number, file_name=f"{subject.item_number}{extension}")
        return ui.messageBox(question, item_command_name(), adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes
    return confirm


_DRAWINGS = {   # format: extension, short name of the format, what writes it
    PDF: (".pdf", "PDF", drawing_source.export_pdf),
    DWG: (".dwg", "DWG", drawing_source.export_dwg),
    DXF: (".dxf", "DXF", drawing_source.export_dxf),
}


def drawing_job(key: str) -> UploadJob:
    """The job that attaches the open drawing as a file of format ``key`` (``export_options.PDF``...). Made when asked for, in the user's language."""
    extension, short, export = _DRAWINGS[key]
    return UploadJob(t("app.job_title_drawing", format=short), t("app.job_label_drawing", format=short), extension,
                     (t("app.job_step_find"), t("app.job_step_create", format=short), t("app.job_step_upload")),
                     lambda path, _subject, _progress: export(path), _confirm_drawing(extension))


def step_job() -> UploadJob:
    """The job that attaches the open design as a STEP file."""
    return UploadJob(t("app.job_title_step"), t("app.job_label_step"), ".step",
                     (t("app.job_step_find"), t("app.job_step_create", format="STEP"), t("app.job_step_upload")), _export_design, _confirm_design)


def export_job(key: str) -> UploadJob:
    """The job that exports the open document as format ``key``."""
    return step_job() if key == STEP else drawing_job(key)

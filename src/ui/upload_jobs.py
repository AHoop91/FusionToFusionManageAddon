"""The kinds of file the add-in attaches to a Fusion Manage item: a STEP file of a design, and a PDF of a drawing."""

import adsk.core
import adsk.fusion

from ..core.constants import ITEM_COMMAND_NAME
from ..publish.exporters import export_step
from . import drawing_source
from .attachment_upload import UploadJob


def _confirm_design(ui: adsk.core.UserInterface, number: str) -> bool:
    """Whether the open design may be attached as the STEP file of item ``number``: it is that item's design, or the user says so."""
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if design is None:
        ui.messageBox("Open the design to publish as a STEP file first.", ITEM_COMMAND_NAME)
        return False
    held = str(design.rootComponent.partNumber or "").strip()
    if held == number:
        return True
    question = f"The open design is {held or 'a design with no part number'}, but the item is {number}.\n\nUpload this design as {number}.step anyway?"
    return ui.messageBox(question, ITEM_COMMAND_NAME, adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes


def _confirm_drawing(ui: adsk.core.UserInterface, number: str) -> bool:
    """Whether the open drawing may be attached as the PDF of item ``number``: it is a drawing of that item, or the user says so."""
    held, reason = drawing_source.top_level_number()
    if not held:
        ui.messageBox(f"The drawing is not ready yet:\n{reason}", ITEM_COMMAND_NAME)
        return False
    if held == number:
        return True
    question = f"The open drawing is of {held}, but the item is {number}.\n\nUpload this drawing as {number}.pdf anyway?"
    return ui.messageBox(question, ITEM_COMMAND_NAME, adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes


STEP_JOB = UploadJob("Uploading STEP File", "STEP file", ".step", ("Find item", "Create STEP", "Upload"), export_step, _confirm_design)
DRAWING_JOB = UploadJob("Uploading Drawing Representation", "drawing PDF", ".pdf", ("Find item", "Create PDF", "Upload"), drawing_source.export_pdf, _confirm_drawing)

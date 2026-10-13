"""What the open drawing is a drawing of, and its PDF.

A drawing document references the design it shows (``Document.documentReferences``). The Fusion Manage item of a drawing is the item
of that design's top-level component, found by its part number. A drawing takes a while to load, so until that part number can be
read the drawing is not ready, and what needs it stays off.
"""

import os
from typing import Any, Optional, Tuple

import adsk.core
import adsk.fusion

from ..core.logging_setup import get_logger

try:
    import adsk.drawing
except ImportError:  # a Fusion without drawings in its API
    adsk.drawing = None

log = get_logger("drawing_source")

_last_reason = ""
_read = {"key": None, "number": ""}   # the part number read for the drawing last looked at


def active_drawing() -> Optional[Any]:
    """The open document's ``adsk.drawing.Drawing``, or None when the open document is not a drawing."""
    if adsk.drawing is None:
        return None
    return adsk.drawing.Drawing.cast(adsk.core.Application.get().activeProduct)


def top_level_number() -> Tuple[str, str]:
    """``(part number, "")`` of the top-level component of the design the open drawing shows, or ``("", why not)`` while that cannot be read.

    Reading a part number is slow and this is asked every few seconds, so a number once read is kept for the document.
    The reason is logged when it changes, so a drawing that never becomes ready says what it is waiting for. Main thread.
    """
    global _last_reason
    number, reason = "", "The open document is not a drawing."
    document = adsk.core.Application.get().activeDocument
    if document is not None and active_drawing() is not None:
        number = cached_number()
        if number:
            return number, ""
        number, reason = _number_of(document)
        if number:
            _read.update(key=_document_key(document), number=number)
    if reason != _last_reason:
        _last_reason = reason
        log.info("Drawing source: %s", f"part number {number}" if number else reason)
    return number, reason


def cached_number() -> str:
    """The part number already read for the open drawing ("" if none yet), without reading anything. Main thread."""
    document = adsk.core.Application.get().activeDocument
    return _read["number"] if document is not None and _read["key"] == _document_key(document) else ""


def _document_key(document: Any) -> str:
    return f"{document.name}|{document.dataFile.id if document.dataFile else ''}"


def _number_of(document: Any) -> Tuple[str, str]:
    references = document.documentReferences
    if not references.count:
        return "", "The drawing has no references yet."
    for reference in references:
        source = reference.referencedDocument
        if source is None:
            continue
        design = adsk.fusion.Design.cast(source.products.itemByProductType("DesignProductType"))
        if design is None:
            continue
        try:
            number = str(design.rootComponent.partNumber or "").strip()
        except RuntimeError as error:   # "Part number cannot be fetched while offline": the design is still loading
            return "", f"The part number of {source.name} cannot be read yet ({error})."
        if number:
            return number, ""
        return "", f"The top-level component of {source.name} has no part number."
    return "", f"{references.count} reference(s), but none of the designs is loaded yet."


def selects_top_level(entities: Any) -> bool:
    """Whether the top of the design tree of the open drawing is among the selected entities, not a component below it.

    A component below the top reaches us as an ``Occurrence``. The top itself is not an occurrence: it is the top-level component
    when Fusion says so, and otherwise an object this API has no type for, so anything else counts.
    """
    top = _top_level_component()
    for entity in entities:
        try:
            if adsk.fusion.Occurrence.cast(entity) is not None:
                continue
        except (TypeError, RuntimeError):   # an object this API has no type for
            pass
        try:
            component = adsk.fusion.Component.cast(entity)
        except (TypeError, RuntimeError):   # an object this API has no type for
            component = None
        log.info("Right-click in a drawing: %s, as a component: %s", type(entity).__name__, component.name if component is not None else None)
        if component is None or top is None or component.entityToken == top.entityToken:
            return True
    return False


def referenced_design() -> Optional[Any]:
    """The design the open drawing shows, or None while it cannot be found."""
    document = adsk.core.Application.get().activeDocument
    for reference in document.documentReferences if document is not None else []:
        source = reference.referencedDocument
        design = adsk.fusion.Design.cast(source.products.itemByProductType("DesignProductType")) if source is not None else None
        if design is not None:
            return design
    return None


def _top_level_component() -> Optional[Any]:
    """The top-level component of the design the open drawing shows, or None while it cannot be found."""
    design = referenced_design()
    return design.rootComponent if design is not None else None


def export_pdf(path: str) -> None:
    """Write every sheet of the open drawing to one PDF at ``path``."""
    drawing = active_drawing()
    if drawing is None:
        raise RuntimeError("The open document is not a drawing.")
    manager = drawing.exportManager
    options = manager.createPDFExportOptions(path)
    options.openPDF = False
    if not manager.execute(options):
        raise RuntimeError("Fusion could not export the drawing as a PDF.")
    if not (os.path.isfile(path) and os.path.getsize(path)):   # an export straight after a drawing opens can report success and write nothing
        raise RuntimeError("Fusion reported the PDF as exported, but no file was written. Wait for the drawing to finish loading and try again.")


def problem() -> str:
    """Why the open document cannot have its drawing uploaded yet ("" when it can): what the drawing is still waiting for."""
    number, reason = top_level_number()
    return "" if number else reason

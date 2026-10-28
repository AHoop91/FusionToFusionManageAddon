"""Files made with the Fusion API. Everything here runs on Fusion's UI thread and blocks it while it works.

A STEP of a component is exported from the open design without opening anything where Fusion allows it, else from the
component's own document.
"""

import time
from typing import Any

from ..core.logging_setup import get_logger

log = get_logger("publish_export")


def _app() -> Any:
    import adsk.core
    return adsk.core.Application.get()


def _design() -> Any:
    import adsk.fusion
    design = adsk.fusion.Design.cast(_app().activeProduct)
    if design is None:
        raise RuntimeError("The open document is not a design.")
    return design


def catch_up() -> None:
    """Let Fusion's graphics engine and event queue catch up (after a document opens or closes, between batch steps)."""
    import adsk
    adsk.doEvents()


def _timed(label: str, action: Any) -> Any:
    """Run action() and log how long it took, so a slow step shows in the log (a step that never returns logs only its start)."""
    log.info("%s ...", label)
    began = time.monotonic()
    try:
        return action()
    finally:
        log.info("%s took %.1fs", label, time.monotonic() - began)


def _export_with(manager: Any, path: str, geometry: Any = None) -> None:
    options = manager.createSTEPExportOptions(path, geometry) if geometry is not None else manager.createSTEPExportOptions(path)
    if not _timed("STEP export", lambda: manager.execute(options)):
        raise RuntimeError("Fusion could not export the STEP file.")


def _own_document_design(occurrence: Any) -> Any:
    """The design of the component's own document, found among the open documents or opened from its data file."""
    app = _app()
    import adsk.fusion
    try:
        data_file = occurrence.documentReference.dataFile   # fails for a component nested in another
    except RuntimeError:
        data_file = None
    if data_file is None:
        raise LookupError("The component's own document could not be found (it is nested in another component).")
    document = next((d for d in app.documents if d.dataFile is not None and d.dataFile.id == data_file.id), None)
    if document is None:
        document = app.documents.open(data_file, False)
    catch_up()
    design = adsk.fusion.Design.cast(document.products.itemByProductType("DesignProductType"))
    if design is None:
        raise RuntimeError("The component's document has no design.")
    return design


def export_step(path: str, occurrence: Any = None) -> None:
    """Write a STEP file: the open design (no ``occurrence``) or one component of it, given by an occurrence of it."""
    if occurrence is None:
        _export_with(_design().exportManager, path)
        return
    manager = _design().exportManager
    failures = []
    for label, geometry in (("occurrence", lambda: occurrence), ("component", lambda: occurrence.component)):
        try:
            _export_with(manager, path, geometry())
            return
        except Exception as exc:  # try the next way
            failures.append(f"{label}: {exc}")
    try:   # last way: export the root of the component's own document
        _export_with(_own_document_design(occurrence).exportManager, path)
    except Exception as exc:
        failures.append(f"own document: {exc}")
        raise RuntimeError("; ".join(failures))

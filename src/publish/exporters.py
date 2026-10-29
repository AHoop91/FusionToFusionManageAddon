"""Files made with the Fusion API. Everything here runs on Fusion's UI thread and blocks it while it works.

A STEP of a component is exported from the open design without opening anything where Fusion allows it, else from the
component's own document.
"""

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, List, Optional

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


def _timed(label: str, action: Callable[[], Any]) -> Any:
    """Run action() and log how long it took, so a slow step shows in the log (a step that never returns logs only its start)."""
    log.info("%s ...", label)
    began = time.monotonic()
    try:
        return action()
    finally:
        log.info("%s took %.1fs", label, time.monotonic() - began)


def _export_with(manager: Any, path: str, geometry: Optional[Any] = None) -> None:
    """Write a STEP file of ``geometry`` (a component or an occurrence; the whole design of ``manager`` when not given) to ``path``.
    Raises ``RuntimeError`` when Fusion says it could not."""
    options = manager.createSTEPExportOptions(path) if geometry is None else manager.createSTEPExportOptions(path, geometry)
    if not _timed("STEP export", lambda: manager.execute(options)):
        raise RuntimeError("Fusion could not export the STEP file.")


def _data_file_of(occurrence: Any) -> Any:
    """The data file of the component's own document, or None for a component nested in another (Fusion fails the lookup then)."""
    try:
        return occurrence.documentReference.dataFile
    except RuntimeError:
        return None


@contextmanager
def _own_document_design(occurrence: Any) -> Iterator[Any]:
    """The design of the component's own document: found among the open documents, else opened (out of sight) from its data file and
    closed again, unsaved, when the caller is done with it."""
    import adsk.fusion
    data_file = _data_file_of(occurrence)
    if data_file is None:
        raise LookupError("The component's own document could not be found (it is nested in another component).")
    documents = _app().documents
    document = next((d for d in documents if d.dataFile is not None and d.dataFile.id == data_file.id), None)
    opened = document is None
    if opened:
        document = documents.open(data_file, False)
    try:
        catch_up()
        design = adsk.fusion.Design.cast(document.products.itemByProductType("DesignProductType"))
        if design is None:
            raise RuntimeError("The component's document has no design.")
        yield design
    finally:
        if opened:   # one this call opened is not left open: a batch of components would pile them up
            try:
                document.close(False)
                catch_up()
            except Exception as exc:   # failing to close must not hide the export's own outcome
                log.warning("Could not close the document opened for the STEP export: %s", exc)


def _export_from_own_document(path: str, occurrence: Any) -> None:
    with _own_document_design(occurrence) as design:
        _export_with(design.exportManager, path)


def export_step(path: str, occurrence: Any = None) -> None:
    """Write a STEP file: the open design (no ``occurrence``) or one component of it, given by an occurrence of it.

    A component is tried as its occurrence, then as its component, then from its own document; ``RuntimeError`` lists why each failed."""
    manager = _design().exportManager
    if occurrence is None:
        _export_with(manager, path)
        return
    ways = (("occurrence", lambda: _export_with(manager, path, occurrence)),
            ("component", lambda: _export_with(manager, path, occurrence.component)),
            ("own document", lambda: _export_from_own_document(path, occurrence)))
    failures: List[str] = []
    for label, way in ways:
        try:
            way()
            return
        except Exception as exc:   # try the next way
            failures.append(f"{label}: {exc}")
    raise RuntimeError("; ".join(failures))

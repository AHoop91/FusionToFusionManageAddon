"""Files made with the Fusion API. Everything here runs on Fusion's UI thread and blocks it while it works.

Components are found in the open design by name, then checked by part number. Reading a
referenced component's properties is slow (about a second each), so the occurrences are listed
once per run (``DesignIndex``) and only the candidate is read. A STEP of a component is
exported from the open design without opening anything where Fusion allows it, else from the
component's own document.
"""

import time
from typing import Any, Dict, List, Optional

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


class DesignIndex:
    """The occurrences of the open design by component name, listed once."""

    def __init__(self) -> None:
        began = time.monotonic()
        log.info("Listing the occurrences of the open design ...")
        self.design = _design()
        self._by_name: Dict[str, List[Any]] = {}
        for occ in self.design.rootComponent.allOccurrences:
            self._by_name.setdefault(str(occ.name).rsplit(":", 1)[0], []).append(occ)
        log.info("Listed %d occurrence(s) in %.1fs", sum(len(v) for v in self._by_name.values()), time.monotonic() - began)

    def find(self, name: str, part_number: str) -> List[Any]:
        """Occurrences of the component called ``name`` whose part number is ``part_number``."""
        candidates = self._by_name.get(name) or []
        if not candidates:
            raise LookupError(f"No component called '{name}' in the open design.")
        for occ in candidates[:3]:   # reading a part number is slow, so only a few are tried
            try:
                if str(occ.component.partNumber or "") == part_number:
                    return candidates
            except Exception as exc:  # offline Fusion cannot fetch it: the name is all there is to match
                log.info("Part number of '%s' not readable (%s); matched by name", name, exc)
                return candidates
        raise LookupError(f"No component called '{name}' with part number {part_number} in the open design.")


def _export_with(manager: Any, path: str, geometry: Any = None) -> None:
    options = manager.createSTEPExportOptions(path, geometry) if geometry is not None else manager.createSTEPExportOptions(path)
    if not _timed("STEP export", lambda: manager.execute(options)):
        raise RuntimeError("Fusion could not export the STEP file.")


def _own_document_design(occurrences: List[Any]) -> Any:
    """The design of the component's own document, found among the open documents or opened from its data file."""
    app = _app()
    import adsk.fusion
    data_file = None
    for occ in occurrences:
        try:
            data_file = occ.documentReference.dataFile   # fails for a component nested in another
            break
        except RuntimeError:
            continue
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


def export_step(path: str, occurrences: Optional[List[Any]] = None, name: str = "", part_number: str = "") -> None:
    """Write a STEP file: the open design (no ``part_number``) or one of its components (``occurrences`` from ``DesignIndex.find``)."""
    if not part_number:
        _export_with(_design().exportManager, path)
        return
    if not occurrences:
        occurrences = DesignIndex().find(name, part_number)
    manager = _design().exportManager
    failures = []
    for label, geometry in (("occurrence", lambda: occurrences[0]), ("component", lambda: occurrences[0].component)):
        try:
            _export_with(manager, path, geometry())
            return
        except Exception as exc:  # try the next way
            failures.append(f"{label}: {exc}")
    try:   # last way: export the root of the component's own document
        _export_with(_own_document_design(occurrences).exportManager, path)
    except Exception as exc:
        failures.append(f"own document: {exc}")
        raise RuntimeError("; ".join(failures))

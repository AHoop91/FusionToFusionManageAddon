"""When what the Export window exports was last saved, from the version history of its document in Fusion (the Data panel).

Each save of a document is a version, and the latest one's creation date is when it was last saved. The timeline of a design has no
dates, so it is not used. Whatever cannot be dated is answered as such (``saved`` None, with the ``reason``), never guessed from another
document: a component of an assembly is dated by its own document, and a drawing by itself and the design it shows.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import adsk.core
import adsk.fusion

from ..core.logging_setup import get_logger
from . import drawing_source

log = get_logger("design_history")


def _answer(saved: Optional[float] = None, saved_in: str = "", unsaved_in: str = "", reason: str = "") -> Dict[str, Any]:
    """What ``compare`` of ``export_freshness`` takes: ``saved`` as a Unix time, or None with the ``reason``; ``saved_in`` names the document
    that was saved last, and ``unsaved_in`` one that has changes not saved ("" when none has)."""
    return {"saved": saved, "saved_in": saved_in, "unsaved": bool(unsaved_in), "unsaved_in": unsaved_in, "reason": reason}


def _stamp(seconds: Optional[float]) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds") if seconds is not None else "-"


def _file_saved(data_file: Any, name: str) -> Tuple[Optional[float], str]:
    """``(Unix time of the latest saved version of the data file, "")``, or ``(None, why not)``."""
    if data_file is None:
        return None, f"{name} has not been saved to Fusion, so it has no version history."
    try:
        latest = data_file.latestVersion or data_file
        return float(latest.dateCreated), ""
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:   # e.g. offline
        return None, f"The version history of {name} could not be read ({exc})."


def _latest(documents: Iterable[Tuple[str, Any]]) -> Tuple[Optional[float], str, str]:
    """``(time, which, "")`` of the latest save among the ``documents`` (each a label, such as "The drawing", and the document), or ``(None, "", why
    not)`` when any cannot be dated: the answer would not be the latest."""
    latest: Tuple[Optional[float], str] = (None, "")
    for label, document in documents:
        saved, reason = _file_saved(document.dataFile, document.name)
        if saved is None:
            return None, "", reason
        if latest[0] is None or saved > latest[0]:
            latest = (saved, f"{label} {document.name}")
    return (latest[0], latest[1], "") if latest[0] is not None else (None, "", "There is no saved document to date.")


def _unsaved(documents: Iterable[Tuple[str, Any]]) -> str:
    """The first of the ``documents`` that has changes not saved, as "The drawing PN-000701"; "" when none has."""
    return next((f"{label} {document.name}" for label, document in documents if document.isModified), "")


def _occurrence_of(entities: Iterable[Any], number: str) -> Optional[Any]:
    """The occurrence among the selected ``entities`` (or the one a selected body or face is seen through) of the component numbered ``number``."""
    for entity in entities:
        try:
            occurrence = adsk.fusion.Occurrence.cast(entity) or getattr(entity, "assemblyContext", None)
            if occurrence is not None and str(occurrence.component.partNumber or "").strip() == number:
                return occurrence
        except (TypeError, RuntimeError, AttributeError):   # an object this API has no type for
            continue
    return None


def _component_saved(occurrence: Any) -> Tuple[Optional[float], str]:
    """When the document of the component ``occurrence`` was last saved; Fusion cannot give that document for a component nested in another."""
    name = occurrence.component.name
    try:
        return _file_saved(occurrence.documentReference.dataFile, name)
    except RuntimeError:
        return None, f"The document of {name} could not be found (it is nested in another component)."


def _of_documents(sources: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """The answer for the ``sources`` (each a label and a document): the latest save among them, and the first with changes not saved."""
    saved, saved_in, reason = _latest(sources)
    return _answer(saved, saved_in, _unsaved(sources), reason)


def saved_state(number: str, entities: Iterable[Any]) -> Dict[str, Any]:
    """When the document that holds what is exported was last saved: the selected component numbered ``number`` (among ``entities``) by its own
    document, else the open design, else the open drawing and the design it shows (the later save of the two). See ``_answer``. UI thread."""
    try:
        app = adsk.core.Application.get()
        document = app.activeDocument
        if document is None:
            return _answer(reason="No document is open.")
        design = adsk.fusion.Design.cast(app.activeProduct)
        drawing = drawing_source.active_drawing() is not None
        occurrence = None if drawing else _occurrence_of(entities, number)
        if drawing:   # a save of the drawing or of the design it shows makes the file out of date
            answer = _of_documents([("The drawing", document)] + [("The design", r.referencedDocument) for r in document.documentReferences
                                                                  if r.referencedDocument is not None])
        elif occurrence is not None:
            saved, reason = _component_saved(occurrence)
            answer = _answer(saved, f"The component {occurrence.component.name}" if saved is not None else "", reason=reason)
        elif design is not None and str(design.rootComponent.partNumber or "").strip() == number:
            answer = _of_documents([("The design", document)])
        else:
            answer = _answer(reason=f"The document that holds {number} could not be found.")
        return _logged(number, answer, document, design)
    except Exception as exc:  # noqa: BLE001 - only a hint for the Export window: it says it could not tell
        log.exception("Could not read when %s was last saved", number)
        return _answer(reason=f"When the document was last saved could not be read ({exc}).")


def _logged(number: str, answer: Dict[str, Any], document: Any, design: Any) -> Dict[str, Any]:
    """``answer``, after it is logged with what else Fusion says of the document, to check it against."""
    data = getattr(design, "rootDataComponent", None)
    log.info("Last saved, for %s: %s in %s (unsaved: %s, document modified: %s, data model timestamp: %s) %s", number, _stamp(answer["saved"]),
             answer["saved_in"] or "-", answer["unsaved_in"] or "-", document.isModified, getattr(data, "timestamp", "-"), answer["reason"])
    return answer

"""When what the Export window exports was last saved (application layer: reads Fusion's document history), from the version history of its document in Fusion (the Data panel).

Each save of a document is a version, and the latest one's creation date is when it was last saved. The timeline of a design has no
dates, so it is not used. Whatever cannot be dated is answered as such (``saved`` None, with the ``reason``), never guessed from another
document: a component of an assembly is dated by its own document, and a drawing by itself and the design it shows.
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import adsk.core
import adsk.fusion

from ..core.i18n import t
from ..core.logging_setup import get_logger
from . import drawing_source

log = get_logger("design_history")


def _doc(kind: str, name: str, inline: bool = False) -> str:
    """How a document is named in a message: ``kind`` is "drawing", "design" or "component"; ``inline`` for the middle of a sentence."""
    if kind == "drawing":
        return t("app.doc_drawing_inline" if inline else "app.doc_drawing", name=name)
    if kind == "component":
        return t("app.doc_component_inline" if inline else "app.doc_component", name=name)
    return t("app.doc_design_inline" if inline else "app.doc_design", name=name)


# The five fields of the answer, each optional and given by keyword: bundling them would only move the same names into another object.
def _answer(saved: Optional[float] = None, saved_in: str = "", unsaved_in: str = "", reason: str = "", saved_in_inline: str = "") -> Dict[str, Any]:
    """What ``compare`` of ``export_freshness`` takes: ``saved`` as a Unix time, or None with the ``reason``; ``saved_in`` names the document
    that was saved last, and ``unsaved_in`` one that has changes not saved ("" when none has)."""
    return {"saved": saved, "saved_in": saved_in, "unsaved": bool(unsaved_in), "unsaved_in": unsaved_in, "reason": reason,
            "saved_in_inline": saved_in_inline}


def _stamp(seconds: Optional[float]) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds") if seconds is not None else "-"


def _file_saved(data_file: Any, name: str) -> Tuple[Optional[float], str]:
    """``(Unix time of the latest saved version of the data file, "")``, or ``(None, why not)``."""
    if data_file is None:
        return None, t("app.history_not_saved", name=name)
    began = time.monotonic()
    try:
        latest = data_file
        if data_file.versionNumber != data_file.latestVersionNumber:   # asking for the latest version may go to the server: only when this is not it
            latest = data_file.latestVersion or data_file
        saved = float(latest.dateCreated)
        log.info("Version history of %s read in %.2fs (version %s of %s)", name, time.monotonic() - began, data_file.versionNumber, data_file.latestVersionNumber)
        return saved, ""
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:   # e.g. offline
        return None, t("app.history_unreadable", name=name, reason=exc)


def _latest(documents: Iterable[Tuple[str, Any]]) -> Tuple[Optional[float], str, str, str]:
    """``(time, which, which in a sentence, "")`` of the latest save among the ``documents`` (each a kind, "drawing" or "design", and the document),
    or ``(None, "", "", why not)`` when any cannot be dated: the answer would not be the latest."""
    latest: Tuple[Optional[float], str, str] = (None, "", "")
    for kind, document in documents:
        saved, reason = _file_saved(document.dataFile, document.name)
        if saved is None:
            return None, "", "", reason
        if latest[0] is None or saved > latest[0]:
            latest = (saved, _doc(kind, document.name), _doc(kind, document.name, True))
    return (latest[0], latest[1], latest[2], "") if latest[0] is not None else (None, "", "", t("app.history_no_saved_document"))


def _unsaved(documents: Iterable[Tuple[str, Any]]) -> str:
    """The first of the ``documents`` that has changes not saved, as "The drawing PN-000701"; "" when none has."""
    return next((_doc(kind, document.name) for kind, document in documents if document.isModified), "")


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
    except (RuntimeError, AttributeError):   # only a top-level reference has a document reference: a nested one is dated by the design its component belongs to
        pass
    try:
        document = occurrence.component.parentDesign.parentDocument
        log.info("%s is nested: dated by its design's document %s", name, document.name)
        return _file_saved(document.dataFile, document.name)
    except (RuntimeError, AttributeError):
        return None, t("app.history_document_not_found", name=name)


def _of_documents(sources: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """The answer for the ``sources`` (each a label and a document): the latest save among them, and the first with changes not saved."""
    saved, saved_in, inline, reason = _latest(sources)
    return _answer(saved, saved_in, _unsaved(sources), reason, inline)


def saved_state(number: str, entities: Iterable[Any]) -> Dict[str, Any]:
    """When the document that holds what is exported was last saved: the selected component numbered ``number`` (among ``entities``) by its own
    document, else the open design, else the open drawing and the design it shows (the later save of the two). See ``_answer``. UI thread."""
    try:
        app = adsk.core.Application.get()
        document = app.activeDocument
        if document is None:
            return _answer(reason=t("app.history_no_document"))
        design = adsk.fusion.Design.cast(app.activeProduct)
        return _logged(number, _answer_for(number, entities, document, design), document, design)
    except Exception as exc:  # noqa: BLE001 - only a hint for the Export window: it says it could not tell
        log.exception("Could not read when %s was last saved", number)
        return _answer(reason=t("app.history_last_saved_unreadable", reason=exc))


def _answer_for(number: str, entities: Iterable[Any], document: Any, design: Any) -> Dict[str, Any]:
    """The answer for the open ``document`` (and ``design``, None in a drawing): see ``saved_state``."""
    if drawing_source.active_drawing() is not None:   # a save of the drawing or of the design it shows makes the file out of date
        shown = [("design", r.referencedDocument) for r in document.documentReferences if r.referencedDocument is not None]
        return _of_documents([("drawing", document)] + shown)
    occurrence = _occurrence_of(entities, number)
    if occurrence is not None:
        return _of_component(occurrence)
    if design is not None:   # no selected component carries the number, so it is the design's (as ``export_target`` took it): its part number is not read again, which is slow
        return _of_documents([("design", document)])
    return _answer(reason=t("app.history_holder_not_found", number=number))


def _of_component(occurrence: Any) -> Dict[str, Any]:
    """The answer for a selected component: the save of its own document."""
    saved, reason = _component_saved(occurrence)
    name = occurrence.component.name
    return _answer(saved, _doc("component", name) if saved is not None else "", reason=reason,
                   saved_in_inline=_doc("component", name, True) if saved is not None else "")


def _logged(number: str, answer: Dict[str, Any], document: Any, design: Any) -> Dict[str, Any]:
    """``answer``, after it is logged with what else Fusion says of the document, to check it against."""
    data = getattr(design, "rootDataComponent", None)
    log.info("Last saved, for %s: %s in %s (unsaved: %s, document modified: %s, data model timestamp: %s) %s", number, _stamp(answer["saved"]),
             answer["saved_in"] or "-", answer["unsaved_in"] or "-", document.isModified, getattr(data, "timestamp", "-"), answer["reason"])
    return answer

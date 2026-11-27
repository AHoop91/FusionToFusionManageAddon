"""What the Export window needs from Fusion and Fusion Manage.

``ExportPanel`` says what is exported and its names, reads the item number and the thumbnail ahead of the click, looks at the files
attached in Fusion Manage, and carries out the export. It owns the state of the one Export window (the part references it read, the last
save it read, and the token of what it is still reading), which is dropped when the window closes.

Layer: UI (Fusion-facing). It sequences worker-thread reads for the Export window, as ``ItemPanel`` does for the Item page. The Item panel
builds it and ``ExportDialog`` talks to it.
"""

import re
import threading
from typing import Any, Callable, Dict, Set, Tuple

import adsk.core

from ..config.hub_context import HubContexts
from ..core.cancel import ADDIN, Cancelled, CancelToken, TokenSlot
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..fm.ttl_cache import TtlCache
from ..publish.writer import safe_name
from . import drawing_source, fusion_selection
from .attachment_upload import AttachmentUpload
from .design_history import saved_state
from .export_options import FORMATS
from .item_numbers import DesignRef, ItemNumbers
from .number_finder import FindOptions, NumberFinder
from .upload_jobs import export_job, pick

log = get_logger("export_panel")


class ExportPanel:
    """What the Export window reads and does, and the state of that window."""

    # Four parameters: the panel's own hub contexts, item numbers, uploads and finder, shared with it (a second ``ItemNumbers`` would
    # split the files it remembers).
    def __init__(self, contexts: HubContexts, numbers: ItemNumbers, uploads: AttachmentUpload, finder: NumberFinder) -> None:
        self._contexts = contexts
        self._numbers = numbers
        self._uploads = uploads
        self._finder = finder
        self._export_refs: Dict[str, DesignRef] = {}   # part number -> where the Data Model finds it, as the window opened
        self._export_read = TtlCache()   # what Fusion says of what the Export window exports (when it was saved), read once per window
        self._export_items: Dict[str, Set[str]] = {}   # part number -> the ids of the items found for it, as the window's table lists them
        self._token = TokenSlot(lambda: ADDIN, "the Export window's look at the attached files")
        self._lock = threading.Lock()   # the items found are told from a worker thread and read on the UI thread

    def export_target(self) -> Tuple[str, str]:
        """``(part number, "")`` of what the Export window exports: the top of the open drawing, or the selected component (else the top) of the
        open design; ``("", why not)`` when there is nothing to export yet. UI thread."""
        if drawing_source.active_drawing() is not None:
            number, reason = drawing_source.top_level_number()
            return (number, "") if number else ("", t("app.drawing_not_ready", reason=reason))
        number = fusion_selection.selected_part_number()
        return (number, "") if number else ("", t("app.select_component"))

    def export_names(self) -> Tuple[str, str]:
        """``(name, description)`` Fusion holds for what Export exports: the selected component of the open design (else the design's top), or
        the design a drawing shows; "" for what it has none of or cannot be read. UI thread."""
        try:
            component, design = fusion_selection.export_component()
            if component is None:
                return "", ""
            name = str(component.name or "").strip()
            if design is not None and component.id == design.rootComponent.id:
                name = re.sub(r" v\d+$", "", name)   # the top is named with the version of the document ("Bracket v12")
            return name, str(component.description or "").strip()
        except (AttributeError, RuntimeError):
            return "", ""

    def _export_ref(self, number: str) -> DesignRef:
        """Where the Data Model finds the part ``number`` the Export window shows (see ``fusion_selection.part_ref``), read once per window: the selection may
        change while it is open. UI thread."""
        if number not in self._export_refs:
            self._export_refs[number] = fusion_selection.part_ref(number)
        return self._export_refs[number]

    def _export_state(self, number: str) -> Dict[str, Any]:
        """The last save (``design_history.saved_state``) of what Export exports, numbered ``number``. Reading it holds Fusion's thread, so it is
        done once per window. UI thread."""
        document = adsk.core.Application.get().activeDocument
        key = (number, document.name if document is not None else "")
        kept = self._export_read.get(key)
        if kept:
            return kept
        return self._export_read.put(key, saved_state(number, fusion_selection.active_selection()))

    def warm_export_target(self, found: Callable[[str, str], None], thumbnail: Callable[[str, str], None]) -> None:
        """Read the item number of what Export will export ahead of the click, on a worker thread, so that the Data Model (about two seconds
        the first time for a design) is already read, and kept, when Export is pressed. ``found(part number, item number)`` is called from the
        worker once it is known, with "" when it could not be read; ``thumbnail(part number, url)`` follows with the component's thumbnail ("" when
        it has none). A failure is left for the click to report. UI thread."""
        number, _problem = self.export_target()
        if not number:
            return
        context, _reason = self._contexts.attempt()   # only an optimisation: the export reports the settings it cannot read
        if context is None:
            return
        ref = self._export_ref(number)
        cancel = self._token.token

        def work() -> None:
            try:
                subject = self._numbers.resolve(ref, number, cancel)
            except Cancelled:   # the window was closed
                return
            except Exception as exc:  # noqa: BLE001 - only an optimisation
                log.info("Item number of %s not read ahead: %s", number, exc)
                found(number, "")   # no item number: the title is left empty
                thumbnail(number, "")
                return
            found(number, subject.item_number)
            try:
                thumbnail(number, self._numbers.thumbnail_url(ref, number, cancel))
            except Cancelled:
                return
            except Exception as exc:  # noqa: BLE001 - the title does without a picture
                log.info("Thumbnail of %s not read: %s", number, exc)
                thumbnail(number, "")
            self._uploads.warm_component(subject, ref, context, cancel)

        threading.Thread(target=work, daemon=True).start()

    def warm_export_items(self, found: Callable[[Dict[str, Any]], None]) -> None:
        """List the items made from what Export exports, for the window's table, on a worker thread of its own (it needs only the part and where the
        Data Model finds it, so it does not wait for the item number or the thumbnail). ``found`` is told ``{"target", "items", "component_url"}``
        (the page of the component's own record, "" when it has none), or with ``"items": []`` and an ``"error"`` saying why they could not be
        listed. UI thread."""
        number, _problem = self.export_target()
        if not number:
            return
        context, reason = self._contexts.attempt()
        ref = self._export_ref(number)
        cancel = self._token.token

        def work() -> None:
            record = ""
            try:
                if context is None:
                    raise ValueError(reason)
                link = self._uploads.link_of(number, ref, cancel)   # read once: the component's page and its items both come from it
                record = self._uploads.page_of(link, context)
                items = self._uploads.items_at(link, context, cancel)
            except Cancelled:   # the window was closed
                return
            except Exception as exc:  # noqa: BLE001 - shown in the window's table, never raised into a thread nobody watches
                log.info("Items of %s not listed: %s", number, exc)
                found({"target": number, "items": [], "error": str(exc), "component_url": record})
                return
            with self._lock:
                self._export_items[number] = {item["id"] for item in items}
            found({"target": number, "items": items, "component_url": record})

        threading.Thread(target=work, daemon=True).start()

    def knows_item(self, number: str, item_id: str) -> bool:
        """Whether ``item_id`` is one of the items the window's table listed for the part ``number``: a file is attached only to one of those."""
        with self._lock:
            return item_id in self._export_items.get(number, ())

    @property
    def export_token(self) -> CancelToken:
        """The token of what the Export window is reading now (see ``cancel_export``)."""
        return self._token.token

    def cancel_export(self) -> None:
        """End what the Export window is still reading from Fusion Manage and the Data Model (it was closed, or is opened again). UI thread."""
        self._token.replace()

    def reset_export(self) -> None:
        """Forget what was read for an earlier Export window: the document may have been saved since. UI thread."""
        self.cancel_export()   # what an earlier window was still reading is not wanted
        self._export_read.clear()
        self._export_refs.clear()
        with self._lock:
            self._export_items.clear()
        self._numbers.forget_files()

    def dispose(self) -> None:
        """End everything the Export window is still reading, for good (the add-in is stopping). UI thread."""
        self._token.cancel()

    def export_files(self, key: str, destination: str, number: str, done: Callable[[Dict[str, Any]], None], item_id: str = "") -> None:
        """Say what exporting the part ``number`` as the format ``key`` to ``destination`` (the item ``item_id`` the table chose, for the item) would
        do to the files attached in Fusion Manage: add one, or make a new version of the one of that name (``AttachmentUpload.preview``). Told to
        ``done`` from a worker thread. UI thread."""
        if not number:
            done({"state": "unavailable", "message": t("app.nothing_to_export")})
            return
        context, reason = self._contexts.attempt()
        if context is None:
            done({"state": "unavailable", "message": reason})
            return
        source = self._export_state(number)
        ref = self._export_ref(number)
        extension = FORMATS[key].extension
        cancel = self._token.token   # the window's: its other looks are not ended by this one, but closing it ends them all

        def work() -> None:
            try:
                subject = self._numbers.resolve(ref, number, cancel)
                done(self._uploads.preview(destination, subject, ref, f"{safe_name(subject.item_number)}{extension}", source, context, cancel, item_id))
            except Cancelled:   # the window was closed: nobody waits for the answer
                log.info("The look at the files for the export of %s was cancelled", number)
            except Exception as exc:  # noqa: BLE001 - shown in the Export window, never raised into a thread nobody watches
                log.info("Files for the export of %s not read: %s", number, exc)
                done({"state": "unavailable", "message": str(exc)})

        threading.Thread(target=work, daemon=True).start()

    def export(self, key: str, destination: str, number: str = "", item_id: str = "") -> None:
        """Export the open document as the format ``key`` and attach it to the item (or the component) ``destination`` of the part
        ``number`` (``export_target`` gives it when none is passed: the window passes the one it shows, which may no longer be the selected one);
        ``item_id`` is the item the table chose, for the item.
        The Export window follows it (``begin_in_window``), so it is told how it went, not shown a message box.
        Raises ``ValueError`` when there is nothing to export or an upload is already under way. UI thread."""
        if not number:
            number, problem = self.export_target()
            if not number:
                raise ValueError(problem)
        job = export_job(key)
        context = self._uploads.begin_in_window(job)
        if context is None:
            raise ValueError(t("app.upload_busy"))
        pick(fusion_selection.active_selection())
        ref = self._export_ref(number)
        self._finder.find(number, lambda subject: self._uploads.continue_in_window(job, context, subject, destination, ref, item_id),
                          FindOptions(fail=self._uploads.fail_in_window, ref=ref))

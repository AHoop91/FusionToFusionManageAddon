"""Make a file from the open document and attach it to a Fusion Manage item (a new version when the file is there already).

What file is made is an ``UploadJob``: a STEP file of a design, or a PDF, DWG or DXF of a drawing. It starts from the Actions menu of the
Item panel (the item shown), from the right-click menu (the item of a number) or from the Export window (the item or the component of
a number). The file is made on Fusion's UI thread; finding the item and the upload run on a worker thread. Each upload (and each look
at what it would do) is made under one ``HubContext``, taken when it is asked for: a hub or setting changed meanwhile does not reach it. How far it has got is kept
in ``status``, and pushed to the pages (``upload_status``) each time it changes; a page also asks for it now and then, in case a push
is missed. The Item panel shows it over itself, and the others start in a small window of their own.
"""

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import adsk.core

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
from ..config.export_models import COMPONENT, ITEM
from ..config.hub_context import HubContext, HubContexts
from ..core.cancel import Cancelled, CancelToken
from ..core.constants import ITEM_COMMAND_NAME
from ..core.logging_setup import get_logger
from ..fm.attachments import NEW_VERSION, AttachmentService
from ..fm.client import FmClient
from ..fm.components import ComponentService, link_ids
from ..fm.items import ItemChoices, ItemService
from ..fm.search_query import WORKING
from ..fm.ttl_cache import TtlCache
from ..publish.exporters import catch_up
from ..publish.run_files import remove_run, temp_root
from ..publish.writer import safe_name
from .export_freshness import compare
from .item_numbers import Subject
from .palette_host import PaletteHost
from .ui_thread import UiThread

log = get_logger("attachment_upload")

Progress = Callable[[Optional[int]], None]   # told the percent done of a stage, or None while that is not known
FIND, MAKE, SEND = 0, 1, 2   # the stages of an upload, by position in ``UploadJob.steps``
PAGE_DRAW_SECONDS = 0.3   # a page asks how far an upload has got every quarter of a second


@dataclass(frozen=True)
class UploadJob:
    """A kind of file to attach."""

    title: str   # "Uploading STEP File"
    label: str   # "STEP file": how the messages name it
    extension: str   # ".step"
    steps: Tuple[str, str, str]   # the short names of the stages: find, make, upload
    make: Callable[[str, Subject, Progress], None]   # write the file at the path given, for the component given, reporting how far it is (UI thread)
    confirm: Callable[[adsk.core.UserInterface, Subject], bool]   # whether the open document may be attached as the file of this item (UI thread)

    def stage(self, step: int) -> str:
        return ("Finding the item", f"Creating the {self.label}", f"Uploading the {self.label}")[step]


class AttachmentUpload:
    """One upload at a time, from the Item panel, the right-click menu or the ribbon."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, host: PaletteHost, window: PaletteHost,
                 config: ConfigService, auth: AuthService, reload: Callable[[], None],
                 announce: Optional[Callable[[Dict[str, Any]], None]] = None, choices: Optional[ItemChoices] = None) -> None:
        self._ui = ui
        self._tasks = tasks
        self._host = host   # the Item panel: it shows the green tick, and the progress of an upload started in it
        self._window = window   # the small progress window of an upload started elsewhere
        self._contexts = HubContexts(config, auth.session)
        self._auth = auth
        self._reload = reload   # read the item shown again (its tab counts change)
        self._choices = choices or ItemChoices()   # which item is meant where several share a number: the Item panel's choice
        self._announce = announce   # told ``status()`` each time it changes, from any thread: the pages are pushed it, and also ask now and then
        self._lock = threading.Lock()
        self._components = TtlCache(60)   # (workspace id, item id) of a component's working version by (stamp, item number), found ahead of an export
        self._status: Dict[str, Any] = {"active": False}   # when over, with the ``result`` of the last one: ``ok`` and a ``message``
        self._window_open = False   # the progress window is shown; only the UI thread changes it
        self._in_window = False   # the upload on show is one the Export window follows: its end is told to the window, not in a message box (under ``_lock``)

    # ---- Starting -------------------------------------------------------------------

    def from_panel(self, job: UploadJob, context: HubContext, workspace_id: str, item_id: str, subject: Subject) -> Dict[str, Any]:
        """Upload for the item shown, which was read under ``context``. UI thread. ``started`` is False when declined or one is under way."""
        if not job.confirm(self._ui, subject):
            return {"started": False}
        if not self._begin(job, MAKE):
            return {"started": False, "busy": True}
        self._tasks.post(lambda: self._make(job, context, workspace_id, item_id, subject))   # after this call returns, so the page is not left waiting
        return {"started": True}

    def from_number(self, job: UploadJob, subject: Subject, destination: str = ITEM) -> None:
        """Upload for the item of ``subject`` (``destination`` ITEM), or for its component in the Components workspace (COMPONENT), asking
        nothing and showing the progress window. UI thread."""
        context, reason = self._contexts.attempt()
        if context is None:
            self._ui.messageBox(f"Could not attach a {job.label}:\n{reason}", ITEM_COMMAND_NAME)
            return
        if not self._begin(job, FIND):
            self._ui.messageBox("A file is already being uploaded.", ITEM_COMMAND_NAME)
            return
        self._window_open = True
        try:
            self._window.show()
        except Exception as exc:  # noqa: BLE001 - the upload is already marked as under way: end it, or no other could start
            log.exception("Could not show the upload window")
            self._fail(f"Could not attach a {job.label}:\n{exc}")
            return
        threading.Thread(target=self._find_then_make, args=(job, context, subject, destination), daemon=True).start()

    def begin_in_window(self, job: UploadJob) -> Optional[HubContext]:
        """Start the status of an upload that the Export window follows (it shows the progress, and the end, itself): the context it is made
        under, to give ``continue_in_window``; None when one is already under way. Raises when the settings cannot be read. UI thread."""
        context = self._contexts.capture()
        if not self._begin(job, FIND, in_window=True):
            return None
        self._in_window = True
        return context

    def continue_in_window(self, job: UploadJob, context: HubContext, subject: Subject, destination: str) -> None:
        """Go on with the upload ``begin_in_window`` started, once the item of ``subject`` is known. UI thread."""
        threading.Thread(target=self._find_then_make, args=(job, context, subject, destination), daemon=True).start()

    def fail_in_window(self, message: str) -> None:
        """End the upload ``begin_in_window`` started, for ``message``. UI thread."""
        self._finish({"ok": False, "message": message})

    def _find_then_make(self, job: UploadJob, context: HubContext, subject: Subject, destination: str) -> None:
        """Find the item (or the component) of ``subject`` in Fusion Manage (a worker thread), then make the file on the UI thread."""
        number = subject.item_number
        began = time.monotonic()
        try:
            workspace_id, item_id = self._find_component(number, context) if destination == COMPONENT else self._find_item(number, context)
        except Cancelled:   # the add-in is stopping
            self._end()
            return
        except Exception as exc:  # shown to the user, never raised into a thread nobody watches
            log.exception("Could not find the %s of %s to attach a %s to", destination, number, job.label)
            self._fail(f"Could not attach a {job.label}:\n{exc}")
            return
        log.info("Found the %s of %s in %.2fs", destination, number, time.monotonic() - began)
        self._tasks.post(lambda: self._make(job, context, workspace_id, item_id, subject, destination))

    def _find_item(self, number: str, context: HubContext, cancel: Optional[CancelToken] = None) -> Tuple[str, str]:
        """``(workspace id, item id)`` of the working version of the item numbered ``number`` in the Items workspace: a released version
        cannot have files attached."""
        if context.items_problem:
            raise ValueError(f"{context.items_problem} Complete it in Preferences.")
        workspace_id = context.cfg.workspace_id
        hits = ItemService(FmClient(context.settings, self._auth, cancel), WORKING).search(workspace_id, number)
        if not hits:
            raise LookupError(f"No item exists for {number}.")
        picked, competing = self._choices.resolve(workspace_id, number, hits)
        if picked is None:   # the choice is made in the Item panel, which lists the items; a file is not attached to one of them by guesswork
            raise LookupError(f"{len(competing)} Fusion Manage items match {number}. Open the item in the Item panel and choose one first.")
        return workspace_id, picked["id"]

    def _find_component(self, number: str, context: HubContext, cancel: Optional[CancelToken] = None) -> Tuple[str, str]:
        """``(workspace id, item id)`` of the working version of the component numbered ``number`` in the Components workspace. A worker thread."""
        key = (context.stamp, number)   # the same number in another tenant is another component
        known = self._components.get(key)
        if known:
            return known
        link, reason = ComponentService(FmClient(context.settings, self._auth, cancel)).find_working(number)
        workspace_id, item_id = link_ids(link)
        if not item_id:
            raise LookupError(reason or f"No component exists for {number}.")
        log.info("Working version of the component %s: workspace %s, item %s (%s)", number, workspace_id, item_id, link)
        return self._components.put(key, (workspace_id, item_id))

    def warm_component(self, number: str, context: HubContext, cancel: Optional[CancelToken] = None) -> None:
        """Find the working version of the component numbered ``number`` ahead of the export, so the export finds it kept. A worker thread;
        a failure is left for the export to report."""
        try:
            self._find_component(number, context, cancel)
        except Cancelled:
            pass
        except Exception as exc:  # noqa: BLE001 - only an optimisation
            log.info("Component %s not found ahead: %s", number, exc)

    def preview(self, destination: str, number: str, name: str, source: Dict[str, Any], context: HubContext,
                cancel: Optional[CancelToken] = None) -> Dict[str, Any]:
        """What attaching the file called ``name`` to the item (or component) numbered ``number`` would do. ``state`` is "ok", with the
        ``existing`` file it would make a new version of (None when it would be attached as new) and whether that file is as recent as the
        ``source`` it is made from (``export_freshness.compare``); or "unavailable", with a ``message``. A worker thread; nothing is changed."""
        try:
            workspace_id, item_id = (self._find_component(number, context, cancel) if destination == COMPONENT
                                     else self._find_item(number, context, cancel))
            files = AttachmentService(FmClient(context.settings, self._auth, cancel)).files(workspace_id, item_id)
        except Cancelled:   # the window moved on to another look: nothing to say
            raise
        except Exception as exc:  # noqa: BLE001 - shown in the Export window, never raised into a thread nobody watches
            log.info("Could not read the files of the %s of %s: %s", destination, number, exc)
            return {"state": "unavailable", "message": str(exc)}
        found = next((file for file in files if file["name"] == name), None)   # the first of that name is the one a new version is made of
        existing = None
        if found:
            existing = {key: found[key] for key in ("version", "updated", "user", "size")} | {"freshness": compare(found["updated"], source)}
            log.info("Attached %s was uploaded %s; last saved %s: %s", name, found["updated"], source, existing["freshness"]["state"])
        return {"state": "ok", "name": name, "existing": existing}

    # ---- Doing ----------------------------------------------------------------------

    def _make(self, job: UploadJob, context: HubContext, workspace_id: str, item_id: str, subject: Subject, destination: str = ITEM) -> None:
        """Write the file and send it off to be attached. UI thread."""
        log.info("Making the %s on Fusion's thread", job.label)
        name = f"{safe_name(subject.item_number)}{job.extension}"
        folder = os.path.join(temp_root(), uuid.uuid4().hex)   # while the file waits to be read
        path = os.path.join(folder, name)
        try:
            os.makedirs(folder, exist_ok=True)
            self._stage(job, MAKE)
            self._let_page_draw()
            job.make(path, subject, lambda percent: self._stage(job, MAKE, percent))
            with open(path, "rb") as handle:
                content = handle.read()
            if not content:   # an export that wrote nothing must not become a new, empty version of a good file
                raise ValueError(f"The {job.label} came out empty.")
        except Exception as exc:  # shown to the user, never raised into Fusion
            log.exception("Could not make %s", name)
            self._fail(f"Could not create {name}:\n{exc}")
            return
        finally:
            remove_run(temp_root(), folder)
        self._stage(job, SEND, 0)
        threading.Thread(target=self._upload, args=(job, context, workspace_id, item_id, name, content, destination), daemon=True).start()

    @staticmethod
    def _let_page_draw() -> None:
        """Making the file holds Fusion's thread (a STEP file about three seconds), and the page's question of how far the upload has got is
        answered on that thread. Give the page one round of asking, so it shows the stage it is about to be stuck on."""
        end = time.monotonic() + PAGE_DRAW_SECONDS
        while time.monotonic() < end:
            catch_up()
            time.sleep(0.05)

    def _upload(self, job: UploadJob, context: HubContext, workspace_id: str, item_id: str, name: str, content: bytes, destination: str) -> None:
        try:
            client = FmClient(context.settings, self._auth)
            kind = AttachmentService(client).upload(workspace_id, item_id, name, content,
                                                    progress=lambda fraction: self._stage(job, SEND, int(fraction * 100)))
        except Cancelled:   # the add-in is stopping
            self._end()
            return
        except Exception as exc:  # shown to the user, never raised into a thread nobody watches
            log.exception("Could not attach %s", name)
            self._fail(f"Could not attach {name}:\n{exc}")
            return
        self._tasks.post(lambda: self._done(name, kind, destination))

    def _done(self, name: str, kind: str, destination: str) -> None:
        """Say the file is attached (to the Export window if it follows it, else a green tick in the panel when it is open, else a message
        box) and read the item again. UI thread."""
        if kind == NEW_VERSION:
            message = f"A new version of {name} was uploaded to the {destination} in Fusion Manage."
        else:
            message = f"{name} was attached to the {destination} in Fusion Manage."
        if self._follows_window():
            self._finish({"ok": True, "message": message})
            self._reload()
            return
        self._end()
        self._close_window()   # now, before the message below, not when the queue gets to it
        if self._host.visible:
            self._host.send("toast", json.dumps({"message": message, "tone": "success"}))
        else:
            self._ui.messageBox(message, ITEM_COMMAND_NAME)
        self._reload()

    def _fail(self, message: str) -> None:
        """Stop and tell the user why, from any thread (the Export window if it follows the upload, else a message box); the progress goes
        first, so it is not left over the message."""
        if self._follows_window():
            self._finish({"ok": False, "message": message})
            return
        self._end()
        self._tasks.post(lambda: self._ui.messageBox(message, ITEM_COMMAND_NAME))

    # ---- Progress -------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """The answer of a page's poll: ``active``, and while it is, the ``title``, the ``stage`` in words, the ``step`` it is at
        among ``steps`` and the ``percent`` (None while unknown). Once one the Export window follows is over, ``result`` says how it went."""
        with self._lock:
            return dict(self._status)

    def _follows_window(self) -> bool:
        """Whether the upload under way is one the Export window follows."""
        with self._lock:
            return self._in_window

    def _tell(self, status: Dict[str, Any]) -> None:
        """Push ``status`` to the pages that follow an upload."""
        if self._announce:
            self._announce(status)

    def _begin(self, job: UploadJob, step: int, in_window: bool = False) -> bool:
        """Start an upload of ``job`` at ``step`` (one the Export window follows if ``in_window``); False when one is already under way."""
        with self._lock:
            if self._status["active"]:
                return False
            self._in_window = in_window
            self._status = {"active": True, "title": job.title, "steps": list(job.steps), "step": step, "stage": job.stage(step), "percent": None}
            status = dict(self._status)
        self._tell(status)
        return True

    def _stage(self, job: UploadJob, step: int, percent: Optional[int] = None) -> None:
        with self._lock:
            if not self._status["active"]:   # a late report of an upload that has ended must not bring it back
                return
            if (self._status["step"], self._status["percent"]) == (step, percent):   # nothing new to say
                return
            self._status.update(step=step, stage=job.stage(step), percent=percent)
            status = dict(self._status)
        self._tell(status)

    def _finish(self, result: Dict[str, Any]) -> None:
        """End an upload the Export window follows, keeping ``result`` for its next poll."""
        with self._lock:
            self._status = {"active": False, "result": result}
            status = dict(self._status)
        self._tell(status)

    def _end(self) -> None:
        with self._lock:
            self._status = {"active": False}
        self._tell({"active": False})
        self._tasks.post(self._close_idle_window)   # the window belongs to the UI thread

    def _close_idle_window(self) -> None:
        """Close the progress window, unless another upload has begun by now: this runs after the upload that posted it ended, and the
        next one may already be showing the window."""
        with self._lock:
            busy = self._status["active"]
        if not busy:
            self._close_window()

    def _close_window(self) -> None:
        if self._window_open:
            self._window_open = False
            self._window.dispose()

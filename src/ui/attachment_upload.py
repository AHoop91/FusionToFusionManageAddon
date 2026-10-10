"""Make a file from the open document and attach it to a Fusion Manage item (a new version when the file is there already).

What file is made is an ``UploadJob``: a STEP file of a design, or a PDF of a drawing. It starts from the Actions menu of the
Item panel (the item shown), or from the right-click menu or the ribbon (the item of a number). The file is made on Fusion's UI
thread; finding the item and the upload run on a worker thread. How far it has got is kept in ``status`` for a page to poll
(``upload_status``): the Item panel shows it over itself, and the other starts in a small window of their own.
"""

import json
import os
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import adsk.core

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
from ..config.workspace_models import ITEMS_KIND
from ..core.constants import ITEM_COMMAND_NAME
from ..core.logging_setup import get_logger
from ..fm.attachments import AttachmentService
from ..fm.client import FmClient
from ..fm.items import ItemService, pick_hit
from ..publish.exporters import catch_up
from ..publish.writer import safe_name
from .palette_host import PaletteHost
from .ui_thread import UiThread

log = get_logger("attachment_upload")

TEMP_FOLDER = "MfgToFm_upload"   # under the temp folder, while a file waits to be attached
Progress = Callable[[Optional[int]], None]   # told the percent done of a stage, or None while that is not known
FIND, MAKE, SEND = 0, 1, 2   # the stages of an upload, by position in ``UploadJob.steps``


@dataclass(frozen=True)
class UploadJob:
    """A kind of file to attach."""

    title: str   # "Uploading STEP File"
    label: str   # "STEP file": how the messages name it
    extension: str   # ".step"
    steps: Tuple[str, str, str]   # the short names of the stages: find, make, upload
    make: Callable[[str, str, Progress], None]   # write the file at the path given, for the item number given, reporting how far it is (UI thread)
    confirm: Callable[[adsk.core.UserInterface, str], bool]   # whether the open document may be attached as the file of this item number (UI thread)

    def stage(self, step: int) -> str:
        return ("Finding the item", f"Creating the {self.label}", f"Uploading the {self.label}")[step]


class AttachmentUpload:
    """One upload at a time, from the Item panel, the right-click menu or the ribbon."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, host: PaletteHost, window: PaletteHost,
                 config: ConfigService, auth: AuthService, reload: Callable[[], None]) -> None:
        self._ui = ui
        self._tasks = tasks
        self._host = host   # the Item panel: it shows the green tick, and the progress of an upload started in it
        self._window = window   # the small progress window of an upload started elsewhere
        self._config = config
        self._auth = auth
        self._reload = reload   # read the item shown again (its tab counts change)
        self._lock = threading.Lock()
        self._status: Dict[str, Any] = {"active": False}
        self._window_open = False

    # ---- Starting -------------------------------------------------------------------

    def from_panel(self, job: UploadJob, workspace_id: str, item_id: str, number: str) -> Dict[str, Any]:
        """Upload for the item shown. UI thread. ``started`` is False when declined or one is under way."""
        if not job.confirm(self._ui, number):
            return {"started": False}
        if not self._begin(job, MAKE):
            return {"started": False, "busy": True}
        self._tasks.post(lambda: self._make(job, workspace_id, item_id, number))   # after this call returns, so the page is not left waiting
        return {"started": True}

    def from_number(self, job: UploadJob, number: str) -> None:
        """Upload for the item of ``number``, asking nothing and showing the progress window. UI thread."""
        if not self._begin(job, FIND):
            self._ui.messageBox("A file is already being uploaded.", ITEM_COMMAND_NAME)
            return
        self._window_open = True
        self._window.show_centered()
        threading.Thread(target=self._find_then_make, args=(job, number), daemon=True).start()

    def _find_then_make(self, job: UploadJob, number: str) -> None:
        """Find the item of ``number`` in Fusion Manage (a worker thread), then make the file on the UI thread."""
        try:
            problem = self._config.items_setup_problem()
            if problem:
                raise ValueError(f"{problem} Complete it in Preferences.")
            workspace_id = self._config.config.workspaces.get(ITEMS_KIND).workspace_id
            hits = ItemService(FmClient(self._config.effective_settings(), self._auth)).search(workspace_id, number)
            if not hits:
                raise LookupError(f"No item exists for {number}.")
        except Exception as exc:  # shown to the user, never raised into a thread nobody watches
            log.exception("Could not find the item of %s to attach a %s to", number, job.label)
            self._fail(f"Could not attach a {job.label}:\n{exc}")
            return
        item_id = pick_hit(hits, number)["id"]
        self._tasks.post(lambda: self._make(job, workspace_id, item_id, number))

    # ---- Doing ----------------------------------------------------------------------

    def _make(self, job: UploadJob, workspace_id: str, item_id: str, number: str) -> None:
        """Write the file and send it off to be attached. UI thread."""
        name = f"{safe_name(number)}{job.extension}"
        folder = os.path.join(tempfile.gettempdir(), TEMP_FOLDER, uuid.uuid4().hex)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        try:
            self._stage(job, MAKE)
            catch_up()   # let the progress window draw before Fusion is busy
            job.make(path, number, lambda percent: self._stage(job, MAKE, percent))
            with open(path, "rb") as handle:
                content = handle.read()
        except Exception as exc:  # shown to the user, never raised into Fusion
            log.exception("Could not make %s", name)
            self._fail(f"Could not create {name}:\n{exc}")
            return
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self._stage(job, SEND, 0)
        threading.Thread(target=self._upload, args=(job, workspace_id, item_id, name, content), daemon=True).start()

    def _upload(self, job: UploadJob, workspace_id: str, item_id: str, name: str, content: bytes) -> None:
        try:
            client = FmClient(self._config.effective_settings(), self._auth)
            kind = AttachmentService(client).upload(workspace_id, item_id, name, content,
                                                    progress=lambda fraction: self._stage(job, SEND, int(fraction * 100)))
        except Exception as exc:  # shown to the user, never raised into a thread nobody watches
            log.exception("Could not attach %s", name)
            self._fail(f"Could not attach {name}:\n{exc}")
            return
        self._tasks.post(lambda: self._done(name, kind))

    def _done(self, name: str, kind: str) -> None:
        """Say the file is attached (a green tick in the panel when it is open, else a message box) and read the item again. UI thread."""
        self._end()
        self._close_window()   # now, before the message below, not when the queue gets to it
        message = f"A new version of {name} was uploaded to the item in Fusion Manage." if kind == "version" else f"{name} was attached to the item in Fusion Manage."
        if self._host.visible:
            self._host.send("toast", json.dumps({"message": message, "tone": "success"}))
        else:
            self._ui.messageBox(message, ITEM_COMMAND_NAME)
        self._reload()

    def _fail(self, message: str) -> None:
        """Stop and tell the user why, from any thread; the progress goes first, so it is not left over the message."""
        self._end()
        self._tasks.post(lambda: self._ui.messageBox(message, ITEM_COMMAND_NAME))

    # ---- Progress -------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """The answer of a page's poll: ``active``, and while it is, the ``title``, the ``stage`` in words, the ``step`` it is at
        among ``steps`` and the ``percent`` (None while unknown)."""
        with self._lock:
            return dict(self._status)

    def _begin(self, job: UploadJob, step: int) -> bool:
        """Start an upload of ``job`` at ``step``; False when one is already under way."""
        with self._lock:
            if self._status["active"]:
                return False
            self._status = {"active": True, "title": job.title, "steps": list(job.steps), "step": step, "stage": job.stage(step), "percent": None}
            return True

    def _stage(self, job: UploadJob, step: int, percent: Optional[int] = None) -> None:
        with self._lock:
            self._status.update(step=step, stage=job.stage(step), percent=percent)

    def _end(self) -> None:
        with self._lock:
            self._status = {"active": False}
        if self._window_open:
            self._tasks.post(self._close_window)

    def _close_window(self) -> None:
        if self._window_open:
            self._window_open = False
            self._window.dispose()

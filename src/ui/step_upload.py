"""Export the open design as ``{item number}.step`` and attach it to a Fusion Manage item (a new version when the file is there already).

It starts from the Actions menu of the Item panel (the item shown) or from the right-click menu (the item of the selected
component). The export needs Fusion's UI thread; finding the item and the upload run on a worker thread. How far it has got
is kept in ``status`` for a page to poll (``step_status``): the Item panel shows it over itself, and the right-click upload in
a small window of its own.
"""

import json
import os
import shutil
import tempfile
import threading
import uuid
from typing import Any, Callable, Dict, Optional

import adsk.core
import adsk.fusion

from ..auth.auth_service import AuthService
from ..config.config_service import ConfigService
from ..config.workspace_models import ITEMS_KIND
from ..core.constants import ITEM_COMMAND_NAME
from ..core.logging_setup import get_logger
from ..fm.attachments import AttachmentService
from ..fm.client import FmClient
from ..fm.items import ItemService, pick_hit
from ..publish.exporters import catch_up, export_step
from ..publish.writer import safe_name
from .palette_host import PaletteHost
from .ui_thread import UiThread

log = get_logger("step_upload")

STEP_FOLDER = "MfgToFm_step"   # under the temp folder, while a STEP file waits to be attached
CREATING, FINDING, UPLOADING = "Creating the STEP file", "Finding the item", "Uploading the STEP file"   # the stages the pages know


class StepUpload:
    """One STEP upload at a time, from the Item panel or the right-click menu."""

    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, host: PaletteHost, window: PaletteHost,
                 config: ConfigService, auth: AuthService, reload: Callable[[], None]) -> None:
        self._ui = ui
        self._tasks = tasks
        self._host = host   # the Item panel: it shows the green tick, and the progress of an upload started in it
        self._window = window   # the small progress window of an upload started from the right-click menu
        self._config = config
        self._auth = auth
        self._reload = reload   # read the item shown again (its tab counts change)
        self._lock = threading.Lock()
        self._status: Dict[str, Any] = {"active": False, "stage": "", "percent": None}
        self._window_open = False

    # ---- Starting -------------------------------------------------------------------

    def from_panel(self, workspace_id: str, item_id: str, number: str) -> Dict[str, Any]:
        """Upload the open design as the file of the item shown. UI thread. ``started`` is False when declined or one is under way."""
        if not self._design_is_for(number):
            return {"started": False}
        if not self._begin(CREATING):
            return {"started": False, "busy": True}
        self._tasks.post(lambda: self._export(workspace_id, item_id, f"{safe_name(number)}.step"))   # after this call returns, so the page is not left waiting
        return {"started": True}

    def from_selection(self, number: str) -> None:
        """Upload the open design as the file of the item of the selected component, asking nothing. UI thread."""
        if not self._begin(FINDING):
            self._ui.messageBox("A STEP file is already being uploaded.", ITEM_COMMAND_NAME)
            return
        self._window_open = True
        self._window.show_centered()
        threading.Thread(target=self._find_then_export, args=(number,), daemon=True).start()

    def _find_then_export(self, number: str) -> None:
        """Find the item of ``number`` in Fusion Manage (a worker thread), then export on the UI thread."""
        try:
            problem = self._config.items_setup_problem()
            if problem:
                raise ValueError(f"{problem} Complete it in Preferences.")
            workspace_id = self._config.config.workspaces.get(ITEMS_KIND).workspace_id
            hits = ItemService(FmClient(self._config.effective_settings(), self._auth)).search(workspace_id, number)
            if not hits:
                raise LookupError(f"No item exists for {number}.")
        except Exception as exc:  # shown to the user, never raised into a thread nobody watches
            log.exception("Could not find the item of %s to attach a STEP file to", number)
            self._fail(f"Could not attach a STEP file:\n{exc}")
            return
        name, item_id = f"{safe_name(number)}.step", pick_hit(hits, number)["id"]
        self._tasks.post(lambda: self._export(workspace_id, item_id, name))

    def _design_is_for(self, number: str) -> bool:
        """Whether the open design may be attached as the file of item ``number``: it is that item's design, or the user says so. UI thread."""
        design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
        if design is None:
            self._ui.messageBox("Open the design to publish as a STEP file first.", ITEM_COMMAND_NAME)
            return False
        held = str(design.rootComponent.partNumber or "").strip()
        if held == number:
            return True
        question = f"The open design is {held or 'a design with no part number'}, but the item is {number}.\n\nUpload this design as {number}.step anyway?"
        return self._ui.messageBox(question, ITEM_COMMAND_NAME, adsk.core.MessageBoxButtonTypes.YesNoButtonType) == adsk.core.DialogResults.DialogYes

    # ---- Doing ----------------------------------------------------------------------

    def _export(self, workspace_id: str, item_id: str, name: str) -> None:
        """Write the open design to a STEP file and send it off to be attached. UI thread."""
        folder = os.path.join(tempfile.gettempdir(), STEP_FOLDER, uuid.uuid4().hex)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        try:
            self._stage(CREATING)
            catch_up()   # let the progress window draw before Fusion is busy exporting
            export_step(path)
            with open(path, "rb") as handle:
                content = handle.read()
        except Exception as exc:  # shown to the user, never raised into Fusion
            log.exception("Could not export %s", name)
            self._fail(f"Could not export {name}:\n{exc}")
            return
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self._stage(UPLOADING, 0)
        threading.Thread(target=self._upload, args=(workspace_id, item_id, name, content), daemon=True).start()

    def _upload(self, workspace_id: str, item_id: str, name: str, content: bytes) -> None:
        try:
            client = FmClient(self._config.effective_settings(), self._auth)
            kind = AttachmentService(client).upload(workspace_id, item_id, name, content,
                                                    progress=lambda fraction: self._stage(UPLOADING, int(fraction * 100)))
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
        """``active``, the ``stage`` in words and ``percent`` (None while unknown): the answer of a page's poll."""
        with self._lock:
            return dict(self._status)

    def _begin(self, stage: str) -> bool:
        """Start an upload at ``stage``; False when one is already under way."""
        with self._lock:
            if self._status["active"]:
                return False
            self._status.update(active=True, stage=stage, percent=None)
            return True

    def _stage(self, stage: str, percent: Optional[int] = None) -> None:
        with self._lock:
            self._status.update(stage=stage, percent=percent)

    def _end(self) -> None:
        with self._lock:
            self._status.update(active=False, stage="", percent=None)
        if self._window_open:
            self._tasks.post(self._close_window)

    def _close_window(self) -> None:
        if self._window_open:
            self._window_open = False
            self._window.dispose()

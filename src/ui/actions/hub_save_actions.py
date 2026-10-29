"""Palette actions to save the hub's Configuration File into a folder of the Fusion Hub, for a Hub Admin, and to make the project or
folder to save it in.

The upload goes through Fusion's own session (``DataFolder.uploadFile``), so it needs no extra sign-in scope. Fusion's API belongs to
Fusion's thread, which is where bridge handlers run, so this does not use a worker: ``save_to_hub`` starts the upload and the panel asks
``save_to_hub_status`` until it has finished.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from ...config.config_service import ConfigService
from ...config.config_transfer import CONFIG_FILE_NAME, config_file_bytes
from ...core.logging_setup import get_logger
from ..message_bridge import MessageBridge
from .hub_file_actions import NO_HUB

log = get_logger("hub_save_actions")

MAX_NAME_LENGTH = 100
FORBIDDEN_IN_NAMES = '\\/:*?"<>|'
PROJECT, FOLDER = "project", "folder"   # what ``create_in_hub`` makes


def _fusion_data() -> Any:
    import adsk.core   # Fusion's module is loaded when asked, so this file imports without Fusion
    return adsk.core.Application.get().data


def _fusion_upload_states() -> Any:
    import adsk.core
    return adsk.core.UploadStates


def _find_folder(data: Any, project_id: str, folder_id: str) -> Any:
    """The folder ``folder_id``, or the root folder of the project when no folder is named; None when Fusion has no such folder."""
    if folder_id:
        return data.findFolderById(folder_id)
    project = data.dataProjects.itemById(project_id)
    return project.rootFolder if project is not None else None


def _checked_name(payload: Dict[str, Any]) -> str:
    """The name asked for, trimmed. Raises ``ValueError`` when it is empty or Fusion would not take it."""
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("Enter a name.")
    if len(name) > MAX_NAME_LENGTH or any(c in FORBIDDEN_IN_NAMES for c in name):
        raise ValueError(f"Use a name of up to {MAX_NAME_LENGTH} characters without any of {FORBIDDEN_IN_NAMES}.")
    return name


@dataclass
class _Upload:
    """The upload that is under way: Fusion's future for it and the folder holding the temporary file Fusion reads it from."""

    future: Any
    folder_name: str
    directory: str

    def discard(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


class HubSaves:
    """Saving the Configuration File to the Fusion Hub, and making the places to save it. Every method runs on Fusion's thread.

    ``data`` gives Fusion's ``Data`` object (the hub, its projects and folders) and ``upload_states`` the values ``uploadState`` can have
    (``adsk.core.UploadStates``); a test gives its own.
    """

    def __init__(self, config: ConfigService, data: Callable[[], Any] = _fusion_data,
                 upload_states: Callable[[], Any] = _fusion_upload_states) -> None:
        self._config, self._data, self._upload_states = config, data, upload_states
        self._upload: Optional[_Upload] = None

    def start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start saving the file to the folder in ``payload`` (``project_id``, and ``folder_id`` for a folder below the project's root)."""
        if not self._config.hub_id:
            raise ValueError(NO_HUB)
        project_id, folder_id = str(payload.get("project_id", "")), str(payload.get("folder_id", ""))
        if not project_id:
            raise ValueError("Choose a folder in a project.")
        folder = _find_folder(self._data(), project_id, folder_id)
        if folder is None:
            raise ValueError("Fusion could not open that folder. Choose it again.")
        self._forget()   # an upload that was never asked about again is not wanted
        directory = tempfile.mkdtemp(prefix="fm-config-")
        try:
            path = os.path.join(directory, CONFIG_FILE_NAME)
            with open(path, "wb") as handle:
                handle.write(config_file_bytes(self._config))
            future = folder.uploadFile(path)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        self._upload = _Upload(future, str(folder.name), directory)
        log.info("Configuration File of hub %r is being saved to the folder %r", self._config.hub_name, folder.name)
        return {"pending": True}

    def status(self) -> Dict[str, Any]:
        """How the upload stands: pending, or done (``ok``). Raises ``ValueError`` when none is under way or Fusion could not save it."""
        upload = self._upload
        if upload is None:
            raise ValueError("No save to the Fusion Hub is under way.")
        states = self._upload_states()
        state = upload.future.uploadState
        if state == states.UploadProcessing:
            return {"pending": True}
        self._forget()
        if state == states.UploadFinished:
            log.info("Configuration File saved to the folder %r", upload.folder_name)
            return {"pending": False, "ok": True, "folder": upload.folder_name, "name": CONFIG_FILE_NAME}
        raise ValueError(f"Fusion could not save the file to {upload.folder_name}. Check that you may add files there.")

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make a project in the hub, or a folder in a project or folder of it. Quick, and Fusion's thread's own to do."""
        name, kind = _checked_name(payload), str(payload.get("kind", ""))
        data = self._data()
        if kind == PROJECT:
            hub = data.activeHub
            if hub is None or hub.id != self._config.hub_id:
                raise ValueError("The hub changed. Close this window and open Preferences again.")
            made = hub.dataProjects.add(name)
        elif kind == FOLDER:
            parent = _find_folder(data, str(payload.get("project_id", "")), str(payload.get("folder_id", "")))
            if parent is None:
                raise ValueError("Fusion could not open the folder to add to. Choose it again.")
            made = parent.dataFolders.add(name)
        else:
            raise ValueError("Unknown kind of item.")
        if made is None:
            raise ValueError(f"Fusion could not create {name}. Check that you may add it here and that the name is not taken.")
        log.info("Created the %s %r in hub %r", kind, name, self._config.hub_name)
        return {"name": name}

    def _forget(self) -> None:
        if self._upload is not None:
            self._upload.discard()
            self._upload = None


def register_hub_save_actions(bridge: MessageBridge, config: ConfigService) -> None:
    """Register ``save_to_hub``, ``save_to_hub_status`` and ``create_in_hub``."""
    saves = HubSaves(config)
    bridge.register("create_in_hub", saves.create)
    bridge.register("save_to_hub", saves.start)
    bridge.register("save_to_hub_status", lambda _payload: saves.status())

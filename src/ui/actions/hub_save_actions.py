"""Palette actions to save the hub's Configuration File into a folder of the Fusion Hub, for a Hub Admin, and to make the project or
folder to save it in.

The upload goes through Fusion's own session (``DataFolder.uploadFile``), so it needs no extra sign-in scope. Fusion's API belongs to
Fusion's thread, which is where bridge handlers run, so this does not use a worker: ``save_to_hub`` starts the upload and the panel asks
``save_to_hub_status`` until it has finished.
"""

import os
import shutil
import tempfile
from typing import Any, Dict, Optional

import adsk.core

from ...config.config_service import ConfigService
from ...config.config_transfer import CONFIG_FILE_NAME, config_file_bytes
from ...core.logging_setup import get_logger
from ..message_bridge import MessageBridge

log = get_logger("hub_save_actions")

MAX_NAME_LENGTH = 100
FORBIDDEN_IN_NAMES = '\\/:*?"<>|'


class _Upload:
    """The upload that is under way: Fusion's future for it and the folder holding the temporary file."""

    def __init__(self, future: Any, folder_name: str, directory: str) -> None:
        self.future, self.folder_name, self.directory = future, folder_name, directory

    def discard(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def register_hub_save_actions(bridge: MessageBridge, config: ConfigService) -> None:
    """Register ``save_to_hub`` and ``save_to_hub_status``."""

    current: Dict[str, Optional[_Upload]] = {"upload": None}

    def forget() -> None:
        if current["upload"] is not None:
            current["upload"].discard()
            current["upload"] = None

    def start(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not config.hub_id:
            raise ValueError("No hub is open. Open a hub in Fusion, then try again.")
        folder_id = str(payload.get("folder_id", ""))
        project_id = str(payload.get("project_id", ""))
        if not project_id:
            raise ValueError("Choose a folder in a project.")
        data = adsk.core.Application.get().data
        folder = data.findFolderById(folder_id) if folder_id else _root_folder(data, project_id)
        if folder is None:
            raise ValueError("Fusion could not open that folder. Choose it again.")
        forget()   # an upload that was never asked about again is not wanted
        directory = tempfile.mkdtemp(prefix="fm-config-")
        try:
            with open(os.path.join(directory, CONFIG_FILE_NAME), "wb") as handle:
                handle.write(config_file_bytes(config))
            future = folder.uploadFile(os.path.join(directory, CONFIG_FILE_NAME))
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        current["upload"] = _Upload(future, str(folder.name), directory)
        log.info("Configuration File of hub %r is being saved to the folder %r", config.hub_name, folder.name)
        return {"pending": True}

    def status(_payload: Dict[str, Any]) -> Dict[str, Any]:
        upload = current["upload"]
        if upload is None:
            raise ValueError("No save to the Fusion Hub is under way.")
        state = upload.future.uploadState
        if state == adsk.core.UploadStates.UploadProcessing:
            return {"pending": True}
        folder_name = upload.folder_name
        forget()
        if state == adsk.core.UploadStates.UploadFinished:
            log.info("Configuration File saved to the folder %r", folder_name)
            return {"pending": False, "ok": True, "folder": folder_name, "name": CONFIG_FILE_NAME}
        raise ValueError(f"Fusion could not save the file to {folder_name}. Check that you may add files there.")

    def create(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make a project in the hub, or a folder in a project or folder of it. Quick, and Fusion's thread's own to do."""
        name = str(payload.get("name", "")).strip()
        kind = str(payload.get("kind", ""))
        if not name:
            raise ValueError("Enter a name.")
        if len(name) > MAX_NAME_LENGTH or any(c in FORBIDDEN_IN_NAMES for c in name):
            raise ValueError(f"Use a name of up to {MAX_NAME_LENGTH} characters without any of {FORBIDDEN_IN_NAMES}.")
        data = adsk.core.Application.get().data
        if kind == "project":
            hub = data.activeHub
            if hub is None or hub.id != config.hub_id:
                raise ValueError("The hub changed. Close this window and open Preferences again.")
            made = hub.dataProjects.add(name)
        elif kind == "folder":
            project_id, folder_id = str(payload.get("project_id", "")), str(payload.get("folder_id", ""))
            parent = data.findFolderById(folder_id) if folder_id else _root_folder(data, project_id)
            if parent is None:
                raise ValueError("Fusion could not open the folder to add to. Choose it again.")
            made = parent.dataFolders.add(name)
        else:
            raise ValueError("Unknown kind of item.")
        if made is None:
            raise ValueError(f"Fusion could not create {name}. Check that you may add it here and that the name is not taken.")
        log.info("Created the %s %r in hub %r", kind, name, config.hub_name)
        return {"name": name}

    bridge.register("create_in_hub", create)
    bridge.register("save_to_hub", start)
    bridge.register("save_to_hub_status", status)


def _root_folder(data: Any, project_id: str) -> Any:
    project = data.dataProjects.itemById(project_id)
    return project.rootFolder if project is not None else None

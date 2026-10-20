"""Palette actions to find the hub's Configuration File in the Fusion Hub and use it as the hub's settings.

Both reads go to the hub over the network, so each runs on a worker thread: the action starts it and answers at once that it is pending, and
the worker pushes the outcome to the panel when it is done. One request of each kind is followed at a time; a newer one replaces an older
one, whose answer is dropped. The ``*_status`` actions give the outcome as it stands, for a panel that missed the push.
"""

import threading
from datetime import datetime
from typing import Any, Callable, Dict

from ...auth.auth_service import AuthService
from ...config.config_envelope import MAX_CONFIG_BYTES, ConfigTransferError
from ...config.config_service import ConfigService
from ...config.config_transfer import config_from_hub_file
from ...core.logging_setup import get_logger
from ...fusion_mfg.hub_files import HubFiles, HubFilesError
from ..message_bridge import MessageBridge
from .settings_actions import settings_payload

log = get_logger("hub_file_actions")

NO_HUB = "No hub is open. Open a hub in Fusion, then try again."


class _Job:
    """The latest request of one kind and how it stands; the outcome is pushed to the panel on the ``action`` name when it is known."""

    def __init__(self, bridge: MessageBridge, action: str) -> None:
        self._bridge, self._action = bridge, action
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {"id": 0, "pending": False, "ok": False, "message": ""}

    def start(self, work: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            request = self._state["id"] + 1
            self._state = {"id": request, "pending": True, "ok": False, "message": ""}
            snapshot = dict(self._state)

        def run() -> None:
            try:
                outcome = dict(work(), ok=True, message="")
            except (HubFilesError, ConfigTransferError) as exc:
                outcome = {"ok": False, "message": str(exc)}
            except Exception as exc:  # noqa: BLE001 - never leave the panel waiting
                log.exception("Hub file request failed")
                outcome = {"ok": False, "message": str(exc) or type(exc).__name__}
            with self._lock:
                if self._state["id"] != request:   # a newer request replaced this one: its answer is not wanted
                    return
                self._state = dict(outcome, id=request, pending=False)
                final = dict(self._state)
            self._bridge.push(self._action, final)   # outside the lock: the push only queues work for Fusion's thread
        threading.Thread(target=run, daemon=True).start()
        return snapshot

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)


def register_hub_file_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register ``browse_hub_files``, ``use_hub_config`` and their ``*_status`` actions."""

    browsing = _Job(bridge, "browse_hub_files_status")
    applying = _Job(bridge, "use_hub_config_status")

    def files() -> HubFiles:
        return HubFiles(config.effective_settings(), auth)

    def browse(payload: Dict[str, Any]) -> Dict[str, Any]:
        hub_id = config.hub_id
        project_id, folder_id = str(payload.get("project_id", "")), str(payload.get("folder_id", ""))
        if not hub_id:
            raise ValueError(NO_HUB)

        def work() -> Dict[str, Any]:
            hub = files()
            if not project_id:
                found = hub.projects(hub_id)
            elif not folder_id:
                found = hub.top_folders(hub_id, project_id)
                if len(found.folders) == 1:   # the project's one top folder is the project itself: show what is in it
                    root = found.folders[0]["id"]
                    inside = hub.contents(project_id, root)
                    return {"folders": inside.folders, "files": inside.files, "folder_id": root}
            else:
                found = hub.contents(project_id, folder_id)
            return {"folders": found.folders, "files": found.files}
        return browsing.start(work)

    def use(payload: Dict[str, Any]) -> Dict[str, Any]:
        hub_id, hub_name = config.hub_id, config.hub_name
        if not hub_id:
            raise ValueError(NO_HUB)
        kept = config.config.hub_file or {}
        project_id = str(payload.get("project_id") or kept.get("project_id", ""))
        item_id = str(payload.get("item_id") or kept.get("item_id", ""))
        name = str(payload.get("name") or kept.get("name", ""))
        if not project_id or not item_id:
            raise ValueError("No Configuration File has been chosen.")

        def work() -> Dict[str, Any]:
            raw = files().read_file(project_id, item_id, MAX_CONFIG_BYTES)
            imported = config_from_hub_file(raw, hub_id, hub_name)
            if config.hub_id != hub_id:   # the user changed hub while the file was being read
                raise HubFilesError("The active hub changed while the file was being read. Try again.")
            ref = {"project_id": project_id, "item_id": item_id, "name": name, "read_at": datetime.now().isoformat(timespec="seconds")}
            problems = config.apply_hub_file(imported, ref)
            if problems:
                raise ConfigTransferError("The file's settings are not valid: " + " ".join(problems))
            log.info("Settings of hub %r read from the Configuration File %r", hub_name, name)
            return {"settings": settings_payload(config)}
        return applying.start(work)

    bridge.register("browse_hub_files", browse)
    bridge.register("browse_hub_files_status", lambda _payload: browsing.status())
    bridge.register("use_hub_config", use)
    bridge.register("use_hub_config_status", lambda _payload: applying.status())

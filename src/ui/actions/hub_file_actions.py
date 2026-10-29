"""Palette actions to find the hub's Configuration File in the Fusion Hub, use it as the hub's settings and keep it up to date.

Both reads go to the hub over the network, so each runs on a worker thread: the action starts it and answers at once that it is pending, and
the worker pushes the outcome to the panel when it is done. One request of each kind is followed at a time; a newer one replaces an older
one, whose answer is dropped. The ``*_status`` actions give the outcome as it stands, for a panel that missed the push.
"""

import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict

from ...config.config_envelope import MAX_CONFIG_BYTES, ConfigTransferError
from ...config.config_service import ConfigService
from ...config.config_transfer import config_from_hub_file
from ...core.cancel import ADDIN, Cancelled
from ...core.logging_setup import get_logger
from ...fusion_mfg.fusion_hub_files import FusionHubFiles, HubFilesError
from ..message_bridge import MessageBridge
from .settings_actions import settings_payload

log = get_logger("hub_file_actions")

START_WAIT_SECONDS = 15   # how often, after the add-in starts, it looks for the hub to be open before checking the file
START_WAIT_TRIES = 20   # and how many times: Fusion may take a while to open the hub

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
                outcome = {"message": "", **work(), "ok": True}   # the work may say why it could not tell (`message`)
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


def register_hub_file_actions(bridge: MessageBridge, config: ConfigService, post: Callable[[Callable[[], None]], None]) -> None:
    """Register ``browse_hub_files``, ``use_hub_config``, ``check_hub_file`` and their ``*_status`` actions.

    The hub is read by Fusion as the signed-in user, so no sign-in to the add-in (and no Client ID) is needed to find the file; ``post``
    queues work on Fusion's main thread.
    """

    browsing = _Job(bridge, "browse_hub_files_status")
    applying = _Job(bridge, "use_hub_config_status")
    checking = _Job(bridge, "check_hub_file_status")

    def files() -> FusionHubFiles:
        return FusionHubFiles(post)

    def browse(payload: Dict[str, Any]) -> Dict[str, Any]:
        hub_id = config.hub_id
        project_id, folder_id = str(payload.get("project_id", "")), str(payload.get("folder_id", ""))
        if not hub_id:
            raise ValueError(NO_HUB)

        def work() -> Dict[str, Any]:
            hub = files()
            if not project_id:
                found = hub.projects()
            elif not folder_id:
                found = hub.top_folders(project_id)
                if len(found.folders) == 1:   # the project's one top folder is the project itself: show what is in it
                    root = found.folders[0]["id"]
                    inside = hub.contents(root)
                    return {"folders": inside.folders, "files": inside.files, "folder_id": root}
            else:
                found = hub.contents(folder_id)
            return {"folders": found.folders, "files": found.files}
        return browsing.start(work)

    def apply_file(hub_id: str, hub_name: str, project_id: str, item_id: str, name: str) -> Dict[str, Any]:
        """Read the file and make it this hub's settings; the outcome has the settings as the panel shows them. Runs on a worker thread."""
        raw = files().read_file(item_id, MAX_CONFIG_BYTES)
        imported = config_from_hub_file(raw, hub_id, hub_name)
        if config.hub_id != hub_id:   # the user changed hub while the file was being read
            raise HubFilesError("The active hub changed while the file was being read. Try again.")
        ref = {"project_id": project_id, "item_id": item_id, "name": name, "read_at": datetime.now().isoformat(timespec="seconds")}
        try:
            ref.update(files().file_info(item_id))   # when it was last updated in the hub, and by whom, for the panel
        except HubFilesError:
            log.info("The details of the Configuration File could not be read")
        problems = config.apply_hub_file(imported, ref)
        if problems:
            raise ConfigTransferError("The file's settings are not valid: " + " ".join(problems))
        log.info("Settings of hub %r read from the Configuration File %r", hub_name, name)
        return {"settings": settings_payload(config)}

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
        return applying.start(lambda: apply_file(hub_id, hub_name, project_id, item_id, name))

    # ---- Keeping up with the Hub Admin's changes ----------------------------------

    check_lock = threading.Lock()   # one look at a time, whether the panel's button or the start-up asked

    def check_file() -> Dict[str, Any]:
        """Look at the file in the hub and, when it is not the one the settings came from, read it again. Never raises: the outcome says
        how it went (`current`, `updated`, `unknown` or `none`). Runs on a worker thread."""
        with check_lock:
            kept = config.config.hub_file
            hub_id, hub_name = config.hub_id, config.hub_name
            if not kept or not hub_id:
                outcome: Dict[str, Any] = {"state": "none"}
            else:
                checked = datetime.now().isoformat(timespec="seconds")
                try:
                    started = time.monotonic()
                    info = files().file_info(kept["item_id"])
                    log.info("Configuration File checked in %.0f ms", (time.monotonic() - started) * 1000)
                    if not info.get("modified") and not info.get("version"):
                        outcome = {"state": "unknown", "checked_at": checked, "message": "The hub did not say when the file was last updated."}
                    elif all(info.get(key, "") == kept.get(key, "") for key in ("modified", "version")):
                        outcome = {"state": "current", "checked_at": checked}
                    else:
                        applied = apply_file(hub_id, hub_name, kept["project_id"], kept["item_id"], kept.get("name", ""))
                        log.info("The Configuration File changed in the hub: its settings were read again")
                        outcome = {"state": "updated", "checked_at": checked, "by": info.get("modified_by", ""), **applied}
                except (HubFilesError, ConfigTransferError) as exc:
                    outcome = {"state": "unknown", "checked_at": checked, "message": str(exc)}
                except Exception as exc:  # noqa: BLE001 - a look that fails is told, never raised
                    log.exception("Could not check the Configuration File")
                    outcome = {"state": "unknown", "checked_at": checked, "message": str(exc) or type(exc).__name__}
            return outcome

    def at_start() -> None:
        """Take the latest version of the Configuration File once, when the add-in starts (Fusion starting, or the add-in being reloaded).
        The hub may not be open yet, so it waits for it a while."""
        try:
            for _ in range(START_WAIT_TRIES):
                if config.config.hub_file and config.hub_id:
                    outcome = check_file()
                    if outcome["state"] in ("updated", "unknown"):
                        bridge.push("hub_file_checked", outcome)   # the panel shows it when it is open
                    return
                ADDIN.wait(START_WAIT_SECONDS)
        except Cancelled:
            return   # the add-in stopped

    def check(_payload: Dict[str, Any]) -> Dict[str, Any]:
        return checking.start(check_file)

    bridge.register("browse_hub_files", browse)
    bridge.register("browse_hub_files_status", lambda _payload: browsing.status())
    bridge.register("use_hub_config", use)
    bridge.register("use_hub_config_status", lambda _payload: applying.status())
    bridge.register("check_hub_file", check)
    bridge.register("check_hub_file_status", lambda _payload: checking.status())
    threading.Thread(target=at_start, daemon=True).start()

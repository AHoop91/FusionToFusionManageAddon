"""Palette actions to find the hub's Configuration File in the Fusion Hub, use it as the hub's settings and keep it up to date.

Both reads go to the hub over the network, so each runs on a worker thread: the action starts it and answers at once that it is pending, and
the worker pushes the outcome to the panel when it is done. One request of each kind is followed at a time; a newer one replaces an older
one, whose answer is dropped. The ``*_status`` actions give the outcome as it stands, for a panel that missed the push.
"""

import threading
import time
from datetime import datetime
from functools import partial
from typing import Any, Callable, Dict

from ...config.config_envelope import MAX_CONFIG_BYTES, ConfigTransferError
from ...config.config_service import ConfigService
from ...config.config_transfer import config_from_hub_file
from ...core.cancel import ADDIN, Cancelled
from ...core.logging_setup import get_logger
from ...fusion_mfg.fusion_hub_files import FusionHubFiles, HubFilesError
from ..message_bridge import MessageBridge
from .background import Runner, in_thread, why
from .settings_actions import settings_payload

log = get_logger("hub_file_actions")

START_WAIT_SECONDS = 15   # how often, after the add-in starts, it looks for the hub to be open before checking the file
START_WAIT_TRIES = 20   # and how many times: Fusion may take a while to open the hub

NO_HUB = "No hub is open. Open a hub in Fusion, then try again."
NO_FILE_CHOSEN = "No Configuration File has been chosen."

# How a look at the file in the hub ended (the panel reads these words).
NONE, CURRENT, UPDATED, UNKNOWN = "none", "current", "updated", "unknown"
CHECKED_ACTION = "hub_file_checked"   # pushed when the check at start-up found something to tell

HubFilesFactory = Callable[[], FusionHubFiles]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class _Job:
    """The latest request of one kind and how it stands; the outcome is pushed to the panel on the ``action`` name when it is known."""

    def __init__(self, bridge: MessageBridge, action: str, run: Runner = in_thread) -> None:
        self._bridge, self._action, self._run = bridge, action, run
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {"id": 0, "pending": False, "ok": False, "message": ""}

    def start(self, work: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            request = self._state["id"] + 1
            self._state = {"id": request, "pending": True, "ok": False, "message": ""}
            snapshot = dict(self._state)
        self._run(lambda: self._finish(request, work))   # outside the lock: a runner may do the work at once, and finishing takes the lock
        return snapshot

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _finish(self, request: int, work: Callable[[], Dict[str, Any]]) -> None:
        try:
            outcome = {"message": "", **work(), "ok": True}   # the work may say why it could not tell (`message`)
        except (HubFilesError, ConfigTransferError) as exc:
            outcome = {"ok": False, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - never leave the panel waiting
            log.exception("Hub file request failed")
            outcome = {"ok": False, "message": why(exc)}
        with self._lock:
            if self._state["id"] != request:   # a newer request replaced this one: its answer is not wanted
                return
            self._state = dict(outcome, id=request, pending=False)
            final = dict(self._state)
        self._bridge.push(self._action, final)   # outside the lock: the push only queues work for Fusion's thread


class HubConfigFile:
    """What is done with the hub's Configuration File: browsing the hub for it, reading it as the hub's settings, and looking whether it
    changed. Each method runs on a worker thread, except ``plan_apply``, which reads the settings and runs on the thread of the request."""

    def __init__(self, config: ConfigService, files: HubFilesFactory) -> None:
        self._config, self._files = config, files
        self._check_lock = threading.Lock()   # one look at a time, whether the panel's button or the start-up asked

    def browse(self, project_id: str, folder_id: str) -> Dict[str, Any]:
        """What the hub holds at that place: its projects, a project's folders, or a folder's contents."""
        hub = self._files()
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

    def apply(self, hub_id: str, hub_name: str, project_id: str, item_id: str, name: str) -> Dict[str, Any]:
        """Read the file and make it this hub's settings; the outcome has the settings as the panel shows them."""
        raw = self._files().read_file(item_id, MAX_CONFIG_BYTES)
        imported = config_from_hub_file(raw, hub_id, hub_name)
        if self._config.hub_id != hub_id:   # the user changed hub while the file was being read
            raise HubFilesError("The active hub changed while the file was being read. Try again.")
        ref = {"project_id": project_id, "item_id": item_id, "name": name, "read_at": _now()}
        try:
            ref.update(self._files().file_info(item_id))   # when it was last updated in the hub, and by whom, for the panel
        except HubFilesError:
            log.info("The details of the Configuration File could not be read")
        problems = self._config.apply_hub_file(imported, ref)
        if problems:
            raise ConfigTransferError("The file's settings are not valid: " + " ".join(problems))
        log.info("Settings of hub %r read from the Configuration File %r", hub_name, name)
        return {"settings": settings_payload(self._config)}

    def plan_apply(self, chosen: Dict[str, Any]) -> Callable[[], Dict[str, Any]]:
        """The work of reading a Configuration File as the settings: the one in ``chosen`` (``project_id``, ``item_id``, ``name``), or the one
        the settings came from last. Raises ``ValueError`` when there is no hub or no file; the hub is the one open now, not when it runs."""
        hub_id, hub_name = self._config.hub_id, self._config.hub_name
        if not hub_id:
            raise ValueError(NO_HUB)
        kept = self._config.config.hub_file or {}
        project_id, item_id, name = (str(chosen.get(key) or kept.get(key, "")) for key in ("project_id", "item_id", "name"))
        if not project_id or not item_id:
            raise ValueError(NO_FILE_CHOSEN)
        return partial(self.apply, hub_id, hub_name, project_id, item_id, name)

    def check(self) -> Dict[str, Any]:
        """Look at the file in the hub and, when it is not the one the settings came from, read it again. Never raises: the outcome says
        how it went (``state``: ``current``, ``updated``, ``unknown`` or ``none``)."""
        with self._check_lock:
            kept = self._config.config.hub_file
            hub_id, hub_name = self._config.hub_id, self._config.hub_name
            if not kept or not hub_id:
                return {"state": NONE}
            checked = _now()
            try:
                return {"checked_at": checked, **self._compare(kept, hub_id, hub_name)}
            except (HubFilesError, ConfigTransferError) as exc:
                return {"state": UNKNOWN, "checked_at": checked, "message": str(exc)}
            except Exception as exc:  # noqa: BLE001 - a look that fails is told, never raised
                log.exception("Could not check the Configuration File")
                return {"state": UNKNOWN, "checked_at": checked, "message": why(exc)}

    def _compare(self, kept: Dict[str, str], hub_id: str, hub_name: str) -> Dict[str, Any]:
        """The outcome of the file in the hub against the one ``kept`` as the settings' source, reading it again when they differ."""
        started = time.monotonic()
        info = self._files().file_info(kept["item_id"])
        log.info("Configuration File checked in %.0f ms", (time.monotonic() - started) * 1000)
        if not info.get("modified") and not info.get("version"):
            return {"state": UNKNOWN, "message": "The hub did not say when the file was last updated."}
        if all(info.get(key, "") == kept.get(key, "") for key in ("modified", "version")):
            return {"state": CURRENT}
        applied = self.apply(hub_id, hub_name, kept["project_id"], kept["item_id"], kept.get("name", ""))
        log.info("The Configuration File changed in the hub: its settings were read again")
        return {"state": UPDATED, "by": info.get("modified_by", ""), **applied}

    def check_at_start(self, bridge: MessageBridge, wait: Callable[[float], Any] = ADDIN.wait) -> None:
        """Take the latest version of the Configuration File once, when the add-in starts (Fusion starting, or the add-in being reloaded).
        The hub may not be open yet, so it waits for it a while (``wait`` raises ``Cancelled`` when the add-in stops)."""
        try:
            for _ in range(START_WAIT_TRIES):
                if self._config.config.hub_file and self._config.hub_id:
                    outcome = self.check()
                    if outcome["state"] in (UPDATED, UNKNOWN):
                        bridge.push(CHECKED_ACTION, outcome)   # the panel shows it when it is open
                    return
                wait(START_WAIT_SECONDS)
        except Cancelled:
            return   # the add-in stopped


def register_hub_file_actions(bridge: MessageBridge, config: ConfigService, post: Callable[[Callable[[], None]], None]) -> None:
    """Register ``browse_hub_files``, ``use_hub_config``, ``check_hub_file`` and their ``*_status`` actions.

    The hub is read by Fusion as the signed-in user, so no sign-in to the add-in (and no Client ID) is needed to find the file; ``post``
    queues work on Fusion's main thread.
    """
    hub_file = HubConfigFile(config, partial(FusionHubFiles, post))
    browsing = _Job(bridge, "browse_hub_files_status")
    applying = _Job(bridge, "use_hub_config_status")
    checking = _Job(bridge, "check_hub_file_status")

    def browse(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not config.hub_id:
            raise ValueError(NO_HUB)
        project_id, folder_id = str(payload.get("project_id", "")), str(payload.get("folder_id", ""))
        return browsing.start(partial(hub_file.browse, project_id, folder_id))

    bridge.register("browse_hub_files", browse)
    bridge.register("browse_hub_files_status", lambda _payload: browsing.status())
    bridge.register("use_hub_config", lambda payload: applying.start(hub_file.plan_apply(payload)))
    bridge.register("use_hub_config_status", lambda _payload: applying.status())
    bridge.register("check_hub_file", lambda _payload: checking.start(hub_file.check))
    bridge.register("check_hub_file_status", lambda _payload: checking.status())
    in_thread(partial(hub_file.check_at_start, bridge))

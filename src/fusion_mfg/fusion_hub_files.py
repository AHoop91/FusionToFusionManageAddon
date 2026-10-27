"""Browsing a Fusion hub's projects and folders, and reading a file in it, through Fusion's own data API.

The user is already signed in to Fusion, so no Client ID or access token is needed: Fusion reads the hub as the user, and shows only what
they can reach. Fusion's API belongs to its main thread, so each read is posted there and waited for; call this from a worker thread.
"""

import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from ..core.logging_setup import get_logger
from .hub_files import HubFilesError, Listing, by_name

log = get_logger("fusion_hub_files")

MAIN_THREAD_WAIT_SECONDS = 120   # a download of a file of a few kilobytes; a stalled Fusion does not keep the panel waiting forever


def run_on_main(post: Callable[[Callable[[], None]], None], work: Callable[[], Any]) -> Any:
    """Run ``work`` on Fusion's main thread (``post`` queues it there) and return what it returns, or raise what it raised."""
    done = threading.Event()
    box: Dict[str, Any] = {}

    def task() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:  # noqa: BLE001 - handed to the waiting thread
            box["error"] = exc
        finally:
            done.set()

    post(task)
    if not done.wait(MAIN_THREAD_WAIT_SECONDS):
        raise HubFilesError("Fusion did not answer in time. Try again.")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _plain(error: str) -> str:
    """What to tell the user about an error from Fusion's data API."""
    text = error.lower()
    if "403" in text or "auth-012" in text or "acm check" in text:
        return ("Fusion would not let you download this file. You may only be able to view this project, and viewers cannot download files. "
                "Ask a Hub Admin to give you a role that can download in this project, or to move the file to a project you can download from.")
    if "404" in text or "not found" in text:
        return "That is no longer in the hub."
    if "offline" in text or "network" in text or "timed out" in text or "timeout" in text:
        return "The hub could not be reached. Check your connection and try again."
    return "Fusion could not read the hub. Try again, and if it keeps happening, ask a Hub Admin for help."


def _iso(moment: Any) -> str:
    """A date from Fusion (a date and time, or seconds since 1970) as ISO text."""
    if hasattr(moment, "isoformat"):
        return moment.isoformat(timespec="seconds")
    return datetime.fromtimestamp(float(moment), tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def _core():
    import adsk.core   # only inside Fusion
    return adsk.core


class FusionHubFiles:
    """Browses the open hub and reads a file in it, as Fusion does for the signed-in user."""

    def __init__(self, post: Callable[[Callable[[], None]], None]) -> None:
        self._post = post

    def _main(self, work: Callable[[], Any]) -> Any:
        started = time.monotonic()
        try:
            return run_on_main(self._post, work)
        except HubFilesError:
            raise
        except Exception as exc:  # noqa: BLE001 - Fusion's own errors are technical: the full text goes to the log, a plain one to the user
            log.warning("Fusion could not read the hub: %s", exc)
            raise HubFilesError(_plain(str(exc))) from exc
        finally:
            log.info("Fusion call on its main thread took %.0f ms", (time.monotonic() - started) * 1000)   # how long Fusion's thread was busy

    @staticmethod
    def _hub():
        hub = _core().Application.get().data.activeHub
        if not hub:
            raise HubFilesError("No hub is open. Open a hub in Fusion, then try again.")
        return hub

    @staticmethod
    def _listing(folder) -> Listing:
        folders = [{"id": f.id, "name": f.name} for f in folder.dataFolders]
        files = [{"id": f.id, "name": f.name} for f in folder.dataFiles]
        return Listing(by_name(folders), by_name(files))

    def projects(self, hub_id: str) -> Listing:
        """The projects of the open hub that the user can reach (shown as folders)."""
        def work() -> Listing:
            return Listing(by_name([{"id": p.id, "name": p.name} for p in self._hub().dataProjects]), [])
        return self._main(work)

    def top_folders(self, hub_id: str, project_id: str) -> Listing:
        """The folder at the top of a project."""
        def work() -> Listing:
            for project in self._hub().dataProjects:
                if project.id == project_id:
                    root = project.rootFolder
                    return Listing([{"id": root.id, "name": root.name}], [])
            raise HubFilesError("That is no longer in the hub.")
        return self._main(work)

    def contents(self, project_id: str, folder_id: str) -> Listing:
        """The folders and files inside a folder."""
        def work() -> Listing:
            folder = _core().Application.get().data.findFolderById(folder_id)
            if not folder:
                raise HubFilesError("That is no longer in the hub.")
            return self._listing(folder)
        return self._main(work)

    def file_info(self, item_id: str) -> Dict[str, str]:
        """What Fusion knows of a file, as text for the panel: its project, when and by whom it was last updated, and its version. What
        Fusion does not say is left out."""
        def work() -> Dict[str, str]:
            data_file = _core().Application.get().data.findFileById(item_id)
            if not data_file:
                return {}
            info: Dict[str, str] = {}
            for key, read in (("project_name", lambda: data_file.parentProject.name),
                              ("modified", lambda: _iso(data_file.dateModified)),
                              ("modified_by", lambda: data_file.lastUpdatedBy.displayName),
                              ("version", lambda: data_file.latestVersionNumber)):
                try:
                    value = read()
                except Exception:  # noqa: BLE001 - a detail Fusion does not give is only missing from the panel
                    continue
                if value not in (None, ""):
                    info[key] = str(value)
            return info
        return self._main(work)

    def read_file(self, project_id: str, item_id: str, max_bytes: int) -> bytes:
        """The content of the latest version of a file. Refused when it is larger than ``max_bytes``."""
        def work() -> bytes:
            data_file = _core().Application.get().data.findFileById(item_id)
            if not data_file:
                raise HubFilesError("That is no longer in the hub.")
            folder = tempfile.mkdtemp(prefix="fusion_manage_config_")
            target = os.path.join(folder, "config.json")
            try:
                data_file.download(target, None)
                if not os.path.exists(target):
                    raise HubFilesError("Fusion did not give the content of that file.")
                if os.path.getsize(target) > max_bytes:
                    raise HubFilesError("The file is too large to be a configuration.")
                with open(target, "rb") as handle:
                    return handle.read()
            finally:
                try:
                    if os.path.exists(target):
                        os.remove(target)
                    os.rmdir(folder)
                except OSError:
                    pass
        return self._main(work)

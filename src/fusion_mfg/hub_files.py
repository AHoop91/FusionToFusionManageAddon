"""Browsing a Fusion hub's projects and folders, and reading a file in it, through the Autodesk Data Management and OSS REST APIs.

The ``data:read`` scope the add-in signs in with is enough. A user is shown only the projects they can reach. Every call is a network
call: use this from a worker thread, never Fusion's.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, NamedTuple, Optional

from ..auth.auth_service import AuthService
from ..auth.errors import AuthError
from ..config.models import ConnectionSettings
from ..core.cancel import ADDIN, CancelToken
from ..core.http import open_url
from ..core.logging_setup import get_logger

log = get_logger("hub_files")

API = "https://developer.api.autodesk.com"
TIMEOUT_SECONDS = 30
MAX_PAGES = 20   # pages of a listing read, so a very large folder cannot keep the picker waiting


class HubFilesError(Exception):
    """A browse or read failed; the message is safe to show to the user."""


class Listing(NamedTuple):
    """What is inside a place in the hub: its folders and its files, each as ``{"id", "name"}``, by name."""

    folders: List[Dict[str, str]]
    files: List[Dict[str, str]]


def _by_name(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(entries, key=lambda e: e["name"].lower())


class HubFiles:
    """Reads the structure and the files of a hub for the signed-in user."""

    def __init__(self, settings: ConnectionSettings, auth: AuthService, cancel: Optional[CancelToken] = None) -> None:
        self._settings = settings
        self._auth = auth
        self.cancel = cancel or ADDIN   # every request checks it, and is ended by it

    # ---- Requests -------------------------------------------------------------

    def _open(self, url: str, authorised: bool = True, headers: Optional[Dict[str, str]] = None) -> bytes:
        request = urllib.request.Request(url, headers=dict(headers or {}))
        if authorised:
            try:
                request.add_header("Authorization", "Bearer " + self._auth.get_access_token(self._settings))
            except AuthError as exc:
                raise HubFilesError(str(exc)) from exc
        try:
            with open_url(request, TIMEOUT_SECONDS, self.cancel) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            log.warning("Hub files: HTTP %s for %s", exc.code, url.split("?")[0])
            if exc.code in (401, 403):
                raise HubFilesError("You do not have access to this in the hub.") from exc
            if exc.code == 404:
                raise HubFilesError("That is no longer in the hub.") from exc
            raise HubFilesError(f"The hub answered with an error ({exc.code}).") from exc
        except (OSError, ValueError) as exc:   # includes a timeout or a dropped connection
            raise HubFilesError(f"The hub could not be reached: {exc}") from exc

    def _json(self, url: str) -> Dict[str, Any]:
        try:
            data = json.loads(self._open(url))
        except ValueError as exc:
            raise HubFilesError("The hub's answer was not understood.") from exc
        if not isinstance(data, dict):
            raise HubFilesError("The hub's answer was not understood.")
        return data

    def _pages(self, url: str) -> List[Dict[str, Any]]:
        """The ``data`` entries of a listing, following its ``next`` links."""
        entries: List[Dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            page = self._json(url)
            entries.extend(e for e in (page.get("data") or []) if isinstance(e, dict))
            url = (((page.get("links") or {}).get("next") or {}).get("href")) or ""
            if not url:
                break
        return entries

    # ---- Browsing -------------------------------------------------------------

    def projects(self, hub_id: str) -> Listing:
        """The projects of the hub that the user can reach (shown as folders)."""
        found = self._pages(f"{API}/project/v1/hubs/{urllib.parse.quote(hub_id, safe='')}/projects?page[limit]=100")
        return Listing(_by_name([{"id": str(e["id"]), "name": str((e.get("attributes") or {}).get("name") or e["id"])} for e in found]), [])

    def top_folders(self, hub_id: str, project_id: str) -> Listing:
        """The folders at the top of a project."""
        url = f"{API}/project/v1/hubs/{urllib.parse.quote(hub_id, safe='')}/projects/{urllib.parse.quote(project_id, safe='')}/topFolders"
        found = self._pages(url)
        return Listing(_by_name([{"id": str(e["id"]), "name": _display(e)} for e in found]), [])

    def contents(self, project_id: str, folder_id: str) -> Listing:
        """The folders and files inside a folder."""
        url = (f"{API}/data/v1/projects/{urllib.parse.quote(project_id, safe='')}"
               f"/folders/{urllib.parse.quote(folder_id, safe='')}/contents?page[limit]=100")
        folders, files = [], []
        entries = self._pages(url)
        log.info("Hub folder holds %d entries: %s", len(entries), sorted({str(e.get("type")) for e in entries}))
        for entry in entries:
            target = {"id": str(entry["id"]), "name": _display(entry)}
            if entry.get("type") == "folders":
                folders.append(target)
            elif entry.get("type") == "items":
                files.append(target)
        return Listing(_by_name(folders), _by_name(files))

    # ---- Reading --------------------------------------------------------------

    def read_file(self, project_id: str, item_id: str, max_bytes: int) -> bytes:
        """The content of the latest version of a file. Refused when it is larger than ``max_bytes``."""
        tip = self._json(f"{API}/data/v1/projects/{urllib.parse.quote(project_id, safe='')}/items/{urllib.parse.quote(item_id, safe='')}/tip")
        data = tip.get("data") or {}
        size = (data.get("attributes") or {}).get("storageSize")
        if isinstance(size, int) and size > max_bytes:
            raise HubFilesError("The file is too large to be a configuration.")
        storage = ((((data.get("relationships") or {}).get("storage") or {}).get("data")) or {}).get("id") or ""
        if "os.object:" not in storage:
            raise HubFilesError("That file has no content that can be read.")
        bucket, _, key = storage.split("os.object:", 1)[1].partition("/")
        signed = self._json(f"{API}/oss/v2/buckets/{urllib.parse.quote(bucket, safe='')}/objects/{urllib.parse.quote(key, safe='')}/signeds3download")
        url = signed.get("url")
        if not isinstance(url, str) or not url.lower().startswith("https://"):
            raise HubFilesError("The hub did not give a way to read that file.")
        content = self._open(url, authorised=False)   # a signed address: the access token is not sent to it
        if len(content) > max_bytes:
            raise HubFilesError("The file is too large to be a configuration.")
        return content


def _display(entry: Dict[str, Any]) -> str:
    attributes = entry.get("attributes") or {}
    return str(attributes.get("displayName") or attributes.get("name") or entry.get("id"))

"""The files attached to a Fusion Manage item: the list the Files tab shows, and downloading one to open.

``GET /api/v3/workspaces/{ws}/items/{id}/attachments`` lists them (the page sorts them). A file's address is empty in
that list, so a download asks the attachment's own ``/file`` link, which needs the sign-in.
"""

import os
import re
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmApiError, FmClient, last_segment

log = get_logger("fm.attachments")

LIST_MEDIA_TYPE = "application/vnd.autodesk.plm.attachments.bulk+json"   # the list; plain application/json is answered with a link
DOWNLOAD_FOLDER = "MfgToFm_attachments"
DOWNLOAD_TIMEOUT_SECONDS = 120   # a big file takes a while
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')   # characters a file name cannot hold on Windows


def parse_files(data: Any) -> List[Dict[str, Any]]:
    """The rows of the Files tab from an attachments answer."""
    rows = data.get("attachments") if isinstance(data, dict) else None
    files = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        kind = row.get("type") if isinstance(row.get("type"), dict) else {}
        created = row.get("created") if isinstance(row.get("created"), dict) else {}
        user = created.get("user") if isinstance(created.get("user"), dict) else {}
        markups = row.get("markups") if isinstance(row.get("markups"), dict) else {}
        name = str(row.get("name") or "")
        files.append({"id": str(row.get("id") or ""), "urn": str(row.get("urn") or ""), "name": name,
                      "title": str(row.get("resourceName") or name),
                      "version": str(row.get("version") or ""),
                      "type": str(kind.get("fileType") or ""), "ext": str(kind.get("extension") or os.path.splitext(name)[1]),
                      "size": int(row.get("size") or 0), "markups": int(markups.get("count") or 0),
                      "updated": str(created.get("timeStamp") or ""), "user": str(user.get("title") or ""),
                      "description": str(row.get("description") or "")})
    return files


class AttachmentService:
    """Lists and downloads an item's attachments through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def files(self, workspace_id: str, item_id: str, item_urn: str = "") -> List[Dict[str, Any]]:
        """The item's files, each with the ``url`` of its page in Fusion Manage's viewer (needs ``item_urn``).
        Raises ``FmApiError`` when the answer is not a list of attachments."""
        path = f"{WORKSPACES}/{workspace_id}/items/{item_id}/attachments?asc=name"
        data = self._client.get_json(path, accept=LIST_MEDIA_TYPE)
        if data is None:   # 204: nothing is attached
            return []
        if not (isinstance(data, dict) and isinstance(data.get("attachments"), list)):
            log.error("%s did not answer with a list of attachments; it held: %s", path,
                      sorted(data) if isinstance(data, dict) else type(data).__name__)
            raise FmApiError("Fusion Manage did not return the list of files for this item.")
        files = parse_files(data)
        for file in files:
            file["url"] = (f"{self._client.base_url}/plm/fileViewer?itemUrn={item_urn}&fileUrn={file['urn']}&vectorPdf=false"
                           if item_urn and file["urn"] else "")
        return files

    def _existing(self, path: str, name: str) -> Tuple[str, Optional[Dict[str, str]]]:
        """``(id, folder)`` of the file already attached under ``name`` ("" when there is none); ``folder`` is ``{"id"}`` or None for the top."""
        data = self._client.get_json(f"{path}?asc=name", accept=LIST_MEDIA_TYPE)
        for row in data.get("attachments") if isinstance(data, dict) and isinstance(data.get("attachments"), list) else []:
            if isinstance(row, dict) and row.get("name") == name and row.get("id"):
                folder = row.get("folder") if isinstance(row.get("folder"), dict) else None
                return str(row["id"]), ({"id": folder["id"]} if folder and folder.get("id") else None)
        return "", None

    def upload(self, workspace_id: str, item_id: str, name: str, content: bytes, description: str = "",
               progress: Optional[Callable[[float], None]] = None) -> str:
        """Attach a file to the item, or a new version of the file already attached under ``name``; returns ``"version"`` or ``"new"``.

        The v3 API takes three steps: register it (the answer holds a signed address), put the bytes at that address,
        then check it in. A new version is registered by posting to the existing attachment instead of the list.
        """
        path = f"{WORKSPACES}/{workspace_id}/items/{item_id}/attachments"
        existing_id, folder = self._existing(path, name)
        body = {"name": name, "resourceName": name, "description": description or name, "folder": folder, "size": len(content)}
        if existing_id:
            body.update(fileName=name, fileTypeString="file/type")
        made = self._client.send_json("POST", f"{path}/{existing_id}" if existing_id else path, body)
        data = made.data if isinstance(made.data, dict) else {}
        attachment_id = str(data.get("id") or last_segment(made.headers.get("Location")))
        address = str(data.get("url") or "")
        if not (attachment_id and address):
            log.error("The attachment answer held no id or upload address: %s %s", made.headers, made.data)
            raise FmApiError("Fusion Manage did not give an address to upload the file to.")
        extra = data.get("extraHeaders") if isinstance(data.get("extraHeaders"), dict) else {}   # signed into the address, so sent exactly as given
        self._client.put_bytes(address, content, {str(k): str(v) for k, v in extra.items()}, progress=progress)
        self._client.send_json("PATCH", f"{path}/{attachment_id}", {"status": {"name": "CheckIn"}})   # the file is complete
        kind = "version" if existing_id else "new"
        log.info("Uploaded %s (%d bytes) to item %s as %s attachment %s", name, len(content), item_id, kind, attachment_id)
        return kind

    def download(self, workspace_id: str, item_id: str, attachment_id: str, name: str) -> str:
        """Save the attachment under the temp folder and return its path."""
        body, _ = self._client.get_bytes(f"{WORKSPACES}/{workspace_id}/items/{item_id}/attachments/{attachment_id}/file",
                                         timeout=DOWNLOAD_TIMEOUT_SECONDS)
        folder = os.path.join(tempfile.gettempdir(), DOWNLOAD_FOLDER, f"{item_id}_{attachment_id}")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, _UNSAFE.sub("_", name) or f"attachment_{attachment_id}")
        with open(path, "wb") as handle:
            handle.write(body)
        log.info("Downloaded attachment %s of item %s (%d bytes) to %s", attachment_id, item_id, len(body), path)
        return path


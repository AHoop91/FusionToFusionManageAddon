"""The files attached to a Fusion Manage item: the list the Files tab shows, and attaching a new file.

``GET /api/v3/workspaces/{ws}/items/{id}/attachments`` lists them (the page sorts them).
"""

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, dict_rows, dig, whole
from .client import WORKSPACES, FmApiError, FmClient, last_segment

log = get_logger("fm.attachments")

LIST_MEDIA_TYPE = "application/vnd.autodesk.plm.attachments.bulk+json"   # the list; plain application/json is answered with a link


def _text(value: Any) -> str:
    return str(value or "")


def parse_files(data: Any) -> List[Dict[str, Any]]:
    """The rows of the Files tab from an attachments answer."""
    files = []
    for row in dict_rows(dig(data, "attachments")):
        name = _text(row.get("name"))
        files.append({"id": _text(row.get("id")), "urn": _text(row.get("urn")), "name": name,
                      "title": _text(row.get("resourceName") or name), "version": _text(row.get("version")),
                      "type": _text(dig(row, "type", "fileType")),
                      "ext": _text(dig(row, "type", "extension") or os.path.splitext(name)[1]),
                      "size": whole(row.get("size")), "markups": whole(dig(row, "markups", "count")),
                      "updated": _text(dig(row, "created", "timeStamp")), "user": _text(dig(row, "created", "user", "title")),
                      "description": _text(row.get("description"))})
    return files


class AttachmentService:
    """Lists an item's attachments and attaches files to it through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def files(self, workspace_id: str, item_id: str, item_urn: str = "") -> List[Dict[str, Any]]:
        """The item's files, each with the ``url`` of its page in Fusion Manage's viewer (needs ``item_urn``).
        Raises ``FmApiError`` when the answer is not a list of attachments."""
        path = f"{WORKSPACES}/{workspace_id}/items/{item_id}/attachments?asc=name"
        data = self._client.get_json(path, accept=LIST_MEDIA_TYPE)
        if data is None:   # 204: nothing is attached
            return []
        if not isinstance(dig(data, "attachments"), list):
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
        for row in dict_rows(dig(data, "attachments")):
            if row.get("name") == name and row.get("id"):
                folder_id = dig(row, "folder", "id")
                return str(row["id"]), ({"id": folder_id} if folder_id else None)
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
        data = as_dict(made.data)
        attachment_id = str(data.get("id") or last_segment(made.headers.get("Location")))
        address = str(data.get("url") or "")
        if not (attachment_id and address):
            log.error("The attachment answer held no id or upload address: %s %s", made.headers, made.data)
            raise FmApiError("Fusion Manage did not give an address to upload the file to.")
        extra = as_dict(data.get("extraHeaders"))   # signed into the address, so sent exactly as given
        self._client.put_bytes(address, content, {str(k): str(v) for k, v in extra.items()}, progress=progress)
        self._client.send_json("PATCH", f"{path}/{attachment_id}", {"status": {"name": "CheckIn"}})   # the file is complete
        kind = "version" if existing_id else "new"
        log.info("Uploaded %s (%d bytes) to item %s as %s attachment %s", name, len(content), item_id, kind, attachment_id)
        return kind

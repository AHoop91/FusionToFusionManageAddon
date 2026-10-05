"""Send a publish folder to Fusion Manage.

A publish run only writes request files (see ``runner``). This is the second step, run after the files
were reviewed: it reads the folder, creates and updates the items, then changes the Bill of Materials of
each parent, filling in the ids that only exist once the items do (see ``placeholders``). It is a job on
the same ``JobQueue`` and answers ``snapshot`` like a publish run, so the Job Queue shows it the same way.

Each request that Fusion Manage accepts is written to ``send-log.json`` at once. Sending the folder again,
after a failure or a cancel, skips what is logged, so nothing is created twice. An item that fails is not
sent again until the next try and its Bill of Materials is not sent; the other items carry on.
"""

import json
import os
import re
import threading
import uuid
from typing import Any, Dict, List, Optional, Set

from ..auth.errors import AuthError
from ..core.logging_setup import get_logger
from ..fm.client import FmApiError, FmClient, SendResult
from ..fm.items import ItemService
from .placeholders import Unresolved, key_of, markers, resolve
from .runner import CANCELLED, DONE, ERROR, QUEUED, RUNNING, time_now

log = get_logger("publish_send")

SEND_LOG = "send-log.json"
DUPLICATE_LINE = "error.bom.duplicate"   # Fusion Manage's answer to adding an item the BOM already has
_ITEM_ID = re.compile(r"/items/(\d+)")
_TENANT = re.compile(r"item:([^.]+)\.")


class FolderError(Exception):
    """The chosen folder is not a publish folder this version can send."""


def _read(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise FolderError(f"Could not read {os.path.basename(path)}: {exc}") from exc


def load_plan(path: str) -> Dict[str, Any]:
    """``{"manifest", "items": [{"number", "request"}], "boms": [{"parent", "requests"}]}`` read from a publish folder."""
    if not os.path.isfile(os.path.join(path, "manifest.json")):
        raise FolderError("This is not a publish folder: manifest.json is missing.")
    manifest = _read(os.path.join(path, "manifest.json"))
    if not isinstance(manifest, dict) or "items" not in manifest:
        raise FolderError("This folder was written by an older version. Publish again to send it.")
    items = [{"number": number, "request": _read(os.path.join(path, info["request"]))}
             for number, info in manifest["items"].items() if info.get("request")]
    boms: List[Dict[str, Any]] = []
    bom_dir = os.path.join(path, "bom")
    for name in sorted(os.listdir(bom_dir)) if os.path.isdir(bom_dir) else []:
        if name.endswith(".bom.request.json"):
            data = _read(os.path.join(bom_dir, name))
            boms.append({"parent": str(data.get("parent", "")), "requests": list(data.get("requests") or [])})
    return {"manifest": manifest, "items": items, "boms": boms}


def summarize(path: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """What sending the folder would do, for the confirmation: counts, tenant and what an earlier send already did."""
    methods = [i["request"]["method"] for i in plan["items"]]
    lines = sum(len(b["requests"]) for b in plan["boms"])
    return {"root": plan["manifest"].get("root", ""), "tenant": plan["manifest"].get("tenant", ""),
            "workspace_id": plan["manifest"].get("workspace_id", ""), "creates": methods.count("POST"),
            "updates": methods.count("PATCH"), "bom_lines": lines, "sent_before": len(_load_log(path))}


def _load_log(path: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(path, SEND_LOG), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def created_id(result: SendResult) -> str:
    """Id of the item a POST created: from the ``Location`` header, else the answer's link; empty if neither says."""
    for name, value in result.headers.items():
        if name.lower() == "location":
            match = _ITEM_ID.search(value)
            if match:
                return match.group(1)
    if isinstance(result.data, dict):
        for key in ("__self__", "link", "urn"):
            match = _ITEM_ID.search(str(result.data.get(key, "")))
            if match:
                return match.group(1)
    return ""


class SendRun:
    """State and steps of sending one folder. ``snapshot`` is what the panels poll."""

    kind = "send"

    def __init__(self, path: str, plan: Dict[str, Any], fm: FmClient) -> None:
        self.path, self.plan, self._fm = path, plan, fm
        manifest = plan["manifest"]
        self._workspace_id = str(manifest.get("workspace_id") or "")
        self._search = ItemService(fm)
        self.id = uuid.uuid4().hex[:8]
        self._lock = threading.Lock()
        self.name = str(manifest.get("root") or os.path.basename(path))
        self.phase = QUEUED
        self.cancelled = False
        self.message = ""
        self.current = ""
        self.done = 0
        self.rows: List[Dict[str, Any]] = (
            [{"item": i["number"], "description": "Create item" if i["request"]["method"] == "POST" else "Update item",
              "root": False, "status": QUEUED, "detail": ""} for i in plan["items"]] +
            [{"item": b["parent"], "description": f"Bill of Materials, {len(b['requests'])} request(s)",
              "root": False, "status": QUEUED, "detail": ""} for b in plan["boms"]])
        self.total = len(self.rows)
        self.queued_at, self.started_at, self.finished_at = time_now(), 0.0, 0.0
        self._ids: Dict[str, str] = {number.casefold(): str(info.get("id") or "")
                                     for number, info in manifest["items"].items()}   # item number -> id; learned as items are created
        self._shown = {number.casefold(): number for number in manifest["items"]}   # the number as written, for messages
        self._failed: Set[str] = set()
        self._facts: Dict[str, Dict[str, str]] = {}   # item id -> {"tenant", "version"}
        self._sent: Dict[str, Any] = _load_log(path)

    # ---- Worker thread ----------------------------------------------------------

    def work(self) -> None:
        with self._lock:
            if self.phase != QUEUED:   # cancelled while it waited
                return
            self.phase = RUNNING
            self.started_at = time_now()
        try:
            rows = iter(self.rows)
            for job in self.plan["items"]:
                if self.cancelled:
                    break
                self._item(job, next(rows))
            for job in self.plan["boms"]:
                if self.cancelled:
                    break
                self._bom(job, next(rows))
        except Exception as exc:
            log.exception("Send run failed")
            self._finish(ERROR, str(exc) or type(exc).__name__)
            return
        self._finish(CANCELLED if self.cancelled else DONE, "Cancelled." if self.cancelled else "")

    def _item(self, job: Dict[str, Any], row: Dict[str, Any]) -> None:
        number, request = job["number"], job["request"]
        self._set(current=number)
        row["status"] = RUNNING
        key = "item:" + number
        try:
            if key in self._sent:
                self._learn(number, str(self._sent[key].get("id") or ""))
                row["detail"] = "Already sent."
            else:
                result = self._fm.send_json(request["method"], request["url"], request.get("body"))
                match = _ITEM_ID.search(request["url"])
                new_id = created_id(result) if request["method"] == "POST" else (match.group(1) if match else "")
                self._learn(number, new_id)
                self._record(key, {"id": new_id})
                row["detail"] = f"{request['method']} {result.status}" + ("" if new_id else "; the answer did not give the new id")
            row["status"] = DONE
        except (FmApiError, AuthError) as exc:
            log.warning("Sending item %s failed: %s", number, exc)
            if request["method"] == "PATCH" and isinstance(exc, FmApiError) and exc.status == 400:
                self._diagnose(request["url"])
            if request["method"] == "POST":   # a failed update leaves the item there, so its Bill of Materials can still be changed
                self._failed.add(number.casefold())
            row["status"], row["detail"] = ERROR, str(exc)
        with self._lock:
            self.done += 1

    def _diagnose(self, url: str) -> None:
        """After a refused update, log what the item itself says about its sections and state, to see why the request was refused."""
        try:
            data = self._fm.get_json(url)
        except (FmApiError, AuthError) as exc:
            log.warning("Could not read %s to explain the refusal: %s", url, exc)
            return
        if isinstance(data, dict):
            shown = {k: v for k, v in data.items() if k not in ("fields", "metaData")}
            log.warning("The refused item %s says: %s", url, json.dumps(shown)[:3000])

    def _bom(self, job: Dict[str, Any], row: Dict[str, Any]) -> None:
        parent, requests = job["parent"], job["requests"]
        self._set(current=parent)
        row["status"] = RUNNING
        index = 0
        try:
            if parent.casefold() in self._failed:
                raise FmApiError(f"Item {parent} was not sent, so its Bill of Materials was not either.")
            for index, request in enumerate(requests):
                if self.cancelled:
                    row["status"], row["detail"] = CANCELLED, f"Cancelled after {index} request(s)."
                    break
                key = f"bom:{parent}:{index}"
                if key in self._sent:
                    continue
                final = resolve(request, self._values(request))
                try:
                    self._fm.send_json(final["method"], final["url"], final.get("body"))
                except FmApiError as exc:
                    if final["method"] != "POST" or DUPLICATE_LINE not in str(exc):
                        raise
                    log.info("BOM line already there, nothing to add: %s", final["url"])   # e.g. an earlier send added it
                self._record(key, {})
            else:
                row["status"], row["detail"] = DONE, f"{len(requests)} request(s) sent."
        except (FmApiError, AuthError, Unresolved) as exc:
            log.warning("Sending the Bill of Materials of %s failed at request %d: %s", parent, index + 1, exc)
            row["status"], row["detail"] = ERROR, f"Request {index + 1} of {len(requests)}: {exc}"
        with self._lock:
            self.done += 1

    # ---- Ids -----------------------------------------------------------------------

    def _learn(self, number: str, item_id: str) -> None:
        if item_id:
            self._ids[number.casefold()] = item_id

    def _item_id(self, number: str) -> str:
        """Id of the item with this number: known from the folder or the send, else searched in Fusion Manage."""
        shown = self._shown.get(number, number)
        if number in self._failed:
            raise FmApiError(f"Item {shown} was not sent.")
        if not self._ids.get(number):
            hits = self._search.search(self._workspace_id, shown)
            if len(hits) != 1:
                raise FmApiError(f"Item {shown} " + ("is not in Fusion Manage." if not hits else f"matches {len(hits)} items in Fusion Manage."))
            self._ids[number] = hits[0]["id"]
        return self._ids[number]

    def _item_facts(self, item_id: str) -> Dict[str, str]:
        """Tenant code and revision of an item, read from the item itself."""
        if item_id not in self._facts:
            data = self._fm.get_json(f"/api/v3/workspaces/{self._workspace_id}/items/{item_id}")
            data = data if isinstance(data, dict) else {}
            tenant = _TENANT.search(str(data.get("urn", "")))
            self._facts[item_id] = {"tenant": tenant.group(1) if tenant else "", "version": str(data.get("version") or "")}
            log.info("Item %s: tenant %r, version %r", item_id, self._facts[item_id]["tenant"], self._facts[item_id]["version"])
        return self._facts[item_id]

    def _values(self, request: Dict[str, Any]) -> Dict[Any, str]:
        """The value of every marker in ``request`` (those left out make ``resolve`` say which are missing)."""
        values: Dict[Any, str] = {}
        found = markers(request)
        for kind, argument in found:
            if kind == "item":
                values[(kind, argument)] = self._item_id(argument)
            elif kind == "version":
                version = self._item_facts(self._item_id(argument))["version"]
                if version:
                    values[(kind, argument)] = version
        if ("tenant", "") in found:
            first = next((a for k, a in found if k == "item"), "")
            tenant = self._item_facts(self._item_id(first))["tenant"] if first else ""
            if tenant:
                values[key_of("tenant")] = tenant
        return values

    # ---- Any thread -------------------------------------------------------------

    def _record(self, key: str, entry: Dict[str, Any]) -> None:
        """Log an accepted request on disk before going on, so a crash or cancel cannot make a resend duplicate it."""
        self._sent[key] = entry
        target = os.path.join(self.path, SEND_LOG)
        with open(target + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(self._sent, handle, indent=2)
        os.replace(target + ".tmp", target)

    def cancel(self) -> None:
        """Stop: a waiting send never starts, a running one stops after the request in flight."""
        with self._lock:
            self.cancelled = True
            waiting = self.phase == QUEUED
        if waiting:
            self._finish(CANCELLED, "Cancelled.")

    def _set(self, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(self, name, value)

    def _finish(self, phase: str, message: str) -> None:
        with self._lock:
            for row in self.rows:
                if row["status"] == QUEUED:   # never reached
                    row["status"], row["detail"] = CANCELLED, "Cancelled." if self.cancelled else "Not sent: the send failed."
        self._set(phase=phase, message=message, current="", finished_at=time_now())
        log.info("Send run %s %s: %s (%s)", self.id, phase, self.path, message or "ok")

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"id": self.id, "kind": self.kind, "name": self.name, "phase": self.phase, "message": self.message,
                    "current": self.current, "done": self.done, "total": self.total, "queued_at": self.queued_at,
                    "started_at": self.started_at, "finished_at": self.finished_at, "folder": self.path, "counts": {},
                    "rows": [dict(r) for r in self.rows]}

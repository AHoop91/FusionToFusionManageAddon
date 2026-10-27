"""Send requests to Fusion Manage: the ``Dispatcher`` that does it, and the ``SendRun`` that sends a publish folder.

A publish run sends each item as soon as its request is written, then the Bill of Materials of each
parent once every item is there (see ``runner``). ``SendRun`` does the same from a finished folder, a
job on the same ``JobQueue`` that answers ``snapshot`` like a publish run: it is how a failed run is retried.

Both go through one ``Dispatcher``, which fills in the ids that only exist once the items do (see
``placeholders``) and writes every request Fusion Manage accepts to ``send-log.json`` at once. Sending
a folder again skips what is logged, so nothing is created twice. An item whose create failed is not
there for its Bill of Materials; the other items carry on.
"""

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..auth.errors import AuthError
from ..core.logging_setup import get_logger
from ..fm.client import FmApiError, FmClient, SendResult
from ..fm.items import ItemService
from .job_state import JobState
from .placeholders import Unresolved, key_of, markers, resolve
from .states import CANCELLED, DONE, ERROR, RUNNING

log = get_logger("publish_send")

SEND_LOG = "send-log.json"
DUPLICATE_LINE = "error.bom.duplicate"   # Fusion Manage's answer to adding an item the BOM already has
BOM_REQUESTS = 5   # Bill of Materials requests in flight at once, across all parents
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


def _load_log(path: str) -> Dict[str, Any]:
    """What an earlier send did. No log is a folder never sent; an unreadable one is an error, since sending on
    without it would create the items again."""
    file = os.path.join(path, SEND_LOG)
    if not os.path.exists(file):
        return {}
    try:
        with open(file, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise FolderError(f"Could not read {SEND_LOG}: {exc}. Sending without it could create items twice.") from exc
    if not isinstance(data, dict):
        raise FolderError(f"{SEND_LOG} is not a send log. Sending without it could create items twice.")
    return data


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


class Dispatcher:
    """Sends item and Bill of Materials requests, remembering the ids of the items and what was accepted.

    Safe to call from several threads: an item goes out while the lock is held, one at a time. Bill of Materials requests go out together,
    the lock held only to look up ids and to log what was accepted.
    """

    def __init__(self, path: str, fm: FmClient, workspace_id: str, known: Optional[Dict[str, str]] = None) -> None:
        self.path, self._fm, self._workspace_id = path, fm, workspace_id
        self._search = ItemService(fm)
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(BOM_REQUESTS)   # shared by every parent being sent
        self._ids: Dict[str, str] = {}   # item number (any case) -> id; empty when the item is known to exist but not its id
        self._shown: Dict[str, str] = {}   # the number as written, for messages
        self._failed: Set[str] = set()
        self._facts: Dict[str, Dict[str, str]] = {}   # item id -> {"tenant", "version"}
        self._sent: Dict[str, Any] = _load_log(path)
        for number, item_id in (known or {}).items():
            self.learn(number, item_id)

    def learn(self, number: str, item_id: str) -> None:
        """Note an item and its id (empty if not known yet)."""
        with self._lock:
            self._shown.setdefault(number.casefold(), number)
            if item_id or number.casefold() not in self._ids:
                self._ids[number.casefold()] = item_id

    # ---- Items ---------------------------------------------------------------------

    def send_item(self, number: str, request: Dict[str, Any]) -> str:
        """Create or update one item; returns what was done. Raises ``FmApiError`` or ``AuthError`` when Fusion Manage refuses."""
        key = "item:" + number
        with self._lock:
            if key in self._sent:
                log.debug("Item %s was sent before, skipped", number)
                self.learn(number, str(self._sent[key].get("id") or ""))
                return "Already sent."
            log.debug("Sending item %s: %s %s", number, request["method"], request["url"])
            try:
                result = self._fm.send_json(request["method"], request["url"], request.get("body"))
            except (FmApiError, AuthError) as exc:
                log.warning("Sending item %s failed: %s", number, exc)
                if request["method"] == "PATCH" and isinstance(exc, FmApiError) and exc.status == 400:
                    self._diagnose(request["url"])
                if request["method"] == "POST":   # a failed update leaves the item there, so its Bill of Materials can still be changed
                    self._failed.add(number.casefold())
                raise
            match = _ITEM_ID.search(request["url"])
            new_id = created_id(result) if request["method"] == "POST" else (match.group(1) if match else "")
            self.learn(number, new_id)
            self._record(key, {"id": new_id})
            return f"{request['method']} {result.status}" + ("" if new_id else "; the answer did not give the new id")

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

    # ---- Bill of Materials -----------------------------------------------------------

    def send_bom(self, parent: str, requests: List[Dict[str, Any]], cancelled: Callable[[], bool] = lambda: False,
                 progress: Callable[[], None] = lambda: None) -> str:
        """Send the lines of one parent's Bill of Materials: removals and updates first, then additions.

        The requests of one step do not depend on each other, so several go out at once (at most ``BOM_REQUESTS`` across all parents);
        the next step starts when the one before has finished, so a position is freed before another line takes it. A failure ends the
        step it is in, and nothing after it is sent. ``progress`` is called after each request, sent or found already sent.

        Raises ``FmApiError``, ``AuthError`` or ``Unresolved`` naming the first request (in order) that failed.
        """
        with self._lock:
            if parent.casefold() in self._failed:
                raise FmApiError(f"Item {parent} was not created, so its Bill of Materials was not sent.")
        indexed = list(enumerate(requests))
        changes = [(i, r) for i, r in indexed if r["method"] != "POST"]   # removals and updates
        additions = [(i, r) for i, r in indexed if r["method"] == "POST"]
        sent = 0
        for batch in (changes, additions):   # the additions wait until every change is done: a line is freed before another takes its position
            if batch:
                sent += self._send_batch(parent, batch, len(requests), cancelled, progress)
                if cancelled():
                    return f"Cancelled after {sent} request(s)."
        return f"{len(requests)} request(s) sent."

    def _send_batch(self, parent: str, batch: List[Tuple[int, Dict[str, Any]]], count: int, cancelled: Callable[[], bool],
                    progress: Callable[[], None]) -> int:
        """Send the requests of a batch, ``BOM_REQUESTS`` at a time, and return how many were sent. The first to fail is raised once the
        others in flight have finished; those not started by then are left unsent."""
        failed = threading.Event()
        with ThreadPoolExecutor(max_workers=BOM_REQUESTS) as pool:
            sent = pool.map(lambda item: self._send_bom_request(parent, item[0], item[1], count, cancelled, failed, progress), batch)
            return list(sent).count(True)

    def _send_bom_request(self, parent: str, index: int, request: Dict[str, Any], count: int, cancelled: Callable[[], bool],
                          failed: threading.Event, progress: Callable[[], None]) -> bool:
        """One request of a Bill of Materials, on a pool thread: True when it was sent, False when it was skipped (sent before, cancelled, or another request has failed)."""
        if cancelled() or failed.is_set():
            return False
        key = f"bom:{parent}:{index}"
        try:
            with self._lock:   # the ids it needs may be searched for, once, and shared
                if key in self._sent:
                    log.debug("BOM request %d of %s was sent before, skipped", index + 1, parent)
                    progress()
                    return False
                final = resolve(request, self._values(request))
            log.debug("BOM request %d of %s: %s %s", index + 1, parent, final["method"], final["url"])
            try:   # outside the lock, so the others go out at the same time
                with self._slots:
                    self._fm.send_json(final["method"], final["url"], final.get("body"))
            except FmApiError as exc:
                if final["method"] != "POST" or DUPLICATE_LINE not in str(exc):
                    raise
                log.info("BOM line already there, nothing to add: %s", final["url"])   # e.g. an earlier send added it
        except (FmApiError, AuthError, Unresolved) as exc:
            failed.set()
            log.warning("Sending the Bill of Materials of %s failed at request %d: %s", parent, index + 1, exc)
            raise type(exc)(f"Request {index + 1} of {count}: {exc}") if isinstance(exc, FmApiError) else exc
        with self._lock:
            self._record(key, {})
        progress()
        return True

    # ---- Ids -------------------------------------------------------------------------

    def _item_id(self, number: str) -> str:
        """Id of the item with this number: known from the folder or the send, else searched in Fusion Manage."""
        shown = self._shown.get(number, number)
        if number in self._failed:
            raise FmApiError(f"Item {shown} was not created.")
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

    def _record(self, key: str, entry: Dict[str, Any]) -> None:
        """Log an accepted request on disk before going on, so a crash or cancel cannot make a resend duplicate it."""
        self._sent[key] = entry
        target = os.path.join(self.path, SEND_LOG)
        with open(target + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(self._sent, handle, indent=2)
        os.replace(target + ".tmp", target)


class SendRun(JobState):
    """State and steps of sending one folder. ``snapshot`` is what the panels poll."""

    kind = "send"
    sends = True
    stage = "sending"
    unreached = "Not sent: the send failed."

    def __init__(self, path: str, plan: Dict[str, Any], fm: FmClient) -> None:
        manifest = plan["manifest"]
        super().__init__(str(manifest.get("root") or os.path.basename(path)), path)
        self.plan = plan
        self._dispatcher = Dispatcher(path, fm, str(manifest.get("workspace_id") or ""),
                                      {number: str(info.get("id") or "") for number, info in manifest["items"].items()})
        self.rows = ([self.row(i["number"], "Create item" if i["request"]["method"] == "POST" else "Update item") for i in plan["items"]] +
                     [self.row(b["parent"], f"Bill of Materials, {len(b['requests'])} request(s)") for b in plan["boms"]])
        self.total = len(self.rows)

    # ---- Worker thread ----------------------------------------------------------

    def work(self) -> None:
        if not self._start():   # cancelled while it waited
            return
        try:
            rows = iter(self.rows)
            for job in self.plan["items"]:
                if self.cancelled:
                    break
                self._step(rows, lambda job=job: self._dispatcher.send_item(job["number"], job["request"]))
            for job in self.plan["boms"]:   # every item is sent before the first Bill of Materials
                if self.cancelled:
                    break
                self._step(rows, lambda job=job: self._dispatcher.send_bom(job["parent"], job["requests"], lambda: self.cancelled))
        except Exception as exc:
            log.exception("Send run failed")
            self._finish(ERROR, str(exc) or type(exc).__name__)
            return
        self._finish(CANCELLED if self.cancelled else DONE, "Cancelled." if self.cancelled else "")

    def _step(self, rows: Any, action: Callable[[], str]) -> None:
        row = next(rows)
        row["status"] = RUNNING
        try:
            row["detail"] = action()
            row["status"] = CANCELLED if self.cancelled and row["detail"].startswith("Cancelled") else DONE
        except (FmApiError, AuthError, Unresolved) as exc:
            row["status"], row["detail"] = ERROR, str(exc)
        with self._lock:
            self.done += 1

    def _finish(self, phase: str, message: str) -> None:
        self._end(phase, message)
        log.info("Send run %s %s: %s (%s)", self.id, phase, self.path, message or "ok")

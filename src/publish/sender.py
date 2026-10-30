"""Send requests to Fusion Manage: the ``Dispatcher`` that does it, and the ``SendRun`` that sends a publish folder.

A publish run sends each item as soon as its request is written, then the Bill of Materials of each
parent once every item is there (see ``runner``). ``SendRun`` does the same from a finished folder, a
job on the same ``JobQueue`` that answers ``snapshot`` like a publish run: it is how a failed run is retried.

Both go through one ``Dispatcher``, which fills in the ids that only exist once the items do (see
``placeholders``) and logs every request Fusion Manage accepts at once (see ``send_log``). Sending
a folder again skips what is logged, so nothing is created twice. An item whose create failed is not
there for its Bill of Materials; the other items carry on.

Cancelling ends a request at once, even a write. A write that was cut off, or that got no answer (a timeout, a dropped connection), may or
may not have been done, so it is logged as in doubt, and sending again finds out before it sends: an item is looked for by its number (it is
there, or it is created), a line that is already there or already gone is not an error.
"""

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..auth.errors import AuthError
from ..core.cancel import Cancelled
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list
from ..fm.client import FmApiError, FmClient, SendResult
from ..fm.items import ItemService
from ..fm.search_query import WORKING
from .job_state import JobState
from .placeholders import ITEM, TENANT, VERSION, Key, Unresolved, key_of, markers, resolve
from .send_log import FolderError, SendLog
from .states import CANCELLED, DONE, ERROR, RUNNING

log = get_logger("publish_send")

DUPLICATE_LINE = "error.bom.duplicate"   # Fusion Manage's answer to adding an item the BOM already has
CUT_OFF = "Cancelled while it was being sent: Fusion Manage may have done it. Sending again checks first."
CANCELLED_PREFIX = "Cancelled"   # how the detail of a send that the cancel stopped between requests begins (see ``send_bom``)
BOM_REQUESTS = 5   # Bill of Materials requests of one parent in flight at once
WRITES = 5   # requests that change Fusion Manage in flight at once, across items and every parent's Bill of Materials
_ITEM_ID = re.compile(r"/items/(\d+)")
_TENANT = re.compile(r"item:([^.]+)\.")


def was_cancelled(detail: str) -> bool:
    """Whether the detail ``send_bom`` gave says the cancel stopped it between requests."""
    return detail.startswith(CANCELLED_PREFIX)


def _read(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise FolderError(f"Could not read {os.path.basename(path)}: {exc}") from exc


def _in_folder(folder: str, relative: str) -> str:
    """The path of a file the manifest names, which has to be in the folder: what is read from it is sent to Fusion Manage."""
    root, path = os.path.realpath(folder), os.path.realpath(os.path.join(folder, relative))
    try:
        inside = os.path.commonpath([root, path]) == root
    except ValueError:   # another drive
        inside = False
    if not inside:
        raise FolderError(f"The manifest names a file outside the folder: {relative}")
    return path


def _request(name: str, data: Any) -> Dict[str, Any]:
    """A request read from a file, which has to have what a send uses: its method and its url."""
    if not isinstance(data, dict) or not isinstance(data.get("method"), str) or not isinstance(data.get("url"), str):
        raise FolderError(f"{name} is not a request: it has no method and url.")
    return data


def load_plan(path: str) -> Dict[str, Any]:
    """``{"manifest", "items": [{"number", "request"}], "boms": [{"parent", "requests"}]}`` read from a publish folder.

    Raises ``FolderError`` for a folder that is not one, was written by an older version, or holds a file that is not what it says."""
    if not os.path.isfile(os.path.join(path, "manifest.json")):
        raise FolderError("This is not a publish folder: manifest.json is missing.")
    manifest = _read(os.path.join(path, "manifest.json"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), dict):
        raise FolderError("This folder was written by an older version. Publish again to send it.")
    items = []
    for number, info in manifest["items"].items():
        relative = as_dict(info).get("request")
        if relative:
            items.append({"number": number, "request": _request(str(relative), _read(_in_folder(path, str(relative))))})
    boms: List[Dict[str, Any]] = []
    bom_dir = os.path.join(path, "bom")
    for name in sorted(os.listdir(bom_dir)) if os.path.isdir(bom_dir) else []:
        if name.endswith(".bom.request.json"):
            data = as_dict(_read(os.path.join(bom_dir, name)))
            requests = [_request(name, request) for request in as_list(data.get("requests"))]
            boms.append({"parent": str(data.get("parent", "")), "requests": requests})
    return {"manifest": manifest, "items": items, "boms": boms}


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

    Safe to call from several threads, which is how it is used: items and Bill of Materials requests go out together, at most ``WRITES`` at
    once. The lock is held only to look up and change ids, never while a request is made or the log is written: the log goes to disk
    before a send goes on, so a write made under the lock would hold up every other item. (It is re-entrant, and what changes the ids is
    taken with it.)
    """

    def __init__(self, path: str, fm: FmClient, workspace_id: str, known: Optional[Dict[str, str]] = None) -> None:
        self.path, self._fm, self._workspace_id = path, fm, workspace_id
        self._search = ItemService(fm, WORKING)
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(WRITES)   # shared by every item and every parent being sent
        self._ids: Dict[str, str] = {}   # item number (any case) -> id; empty when the item is known to exist but not its id
        self._shown: Dict[str, str] = {}   # the number as written, for messages
        self._failed: Set[str] = set()
        self._facts: Dict[str, Dict[str, str]] = {}   # item id -> {"tenant", "version"}
        self._sent = SendLog(path)
        for number, item_id in (known or {}).items():
            self.learn(number, item_id)

    def learn(self, number: str, item_id: str) -> None:
        """Note an item and its id (empty if not known yet)."""
        with self._lock:
            self._shown.setdefault(number.casefold(), number)
            if item_id or number.casefold() not in self._ids:
                self._ids[number.casefold()] = item_id

    # ---- Items ---------------------------------------------------------------------

    def _created_before(self, number: str) -> str:
        """The id of the item an earlier send was cut off while creating, if it was created: the one item with the number, "" if there is none.
        Raises ``FmApiError`` for several (the number was not free, so it cannot be told which was ours)."""
        shown = self._shown.get(number.casefold(), number)
        hits = self._search.search(self._workspace_id, shown)
        if len(hits) > 1:
            raise FmApiError(f"Item {shown} matches {len(hits)} items in Fusion Manage, so it cannot be told whether the cancelled send created it.")
        return hits[0]["id"] if hits else ""

    def send_item(self, number: str, request: Dict[str, Any]) -> str:
        """Create or update one item; returns what was done. Raises ``FmApiError`` or ``AuthError`` when Fusion Manage refuses, and
        ``Cancelled`` when the send is cancelled (the item is then logged as in doubt)."""
        key, method = "item:" + number, request["method"]
        with self._lock:
            if self._sent.done(key):
                log.debug("Item %s was sent before, skipped", number)
                self.learn(number, str(self._sent.entry(key).get("id") or ""))
                return "Already sent."
            doubtful = self._sent.in_doubt(key)
        if doubtful and method == "POST":   # an update can be sent again; a create may have made the item
            existing = self._created_before(number)
            if existing:
                with self._lock:
                    self.learn(number, existing)
                self._sent.accept(key, {"id": existing})
                return "Already created: found in Fusion Manage after a cancelled send."
        intended = method == "POST" and not doubtful   # an entry of its own is logged first: a crash while the create is under way leaves it in doubt
        if intended:
            self._sent.intend(key)
        log.debug("Sending item %s: %s %s", number, method, request["url"])
        try:   # outside the lock, so the items go out at the same time
            with self._slots:
                result = self._fm.send_json(method, request["url"], request.get("body"))
        except Cancelled:
            self._sent.doubt(key, "was cancelled while it was being sent")
            raise
        except (FmApiError, AuthError) as exc:
            log.warning("Sending item %s failed: %s", number, exc)
            if method == "PATCH" and isinstance(exc, FmApiError) and exc.status == 400:
                self._diagnose(request["url"])
            if method == "POST":   # a failed update leaves the item there, so its Bill of Materials can still be changed
                with self._lock:
                    self._failed.add(number.casefold())
            if isinstance(exc, FmApiError) and exc.outcome_unknown:   # sent, perhaps, and done, perhaps: a resend finds out first
                self._sent.doubt(key, "got no answer or a server error")
            elif intended:   # refused for good: not done, so nothing to find out
                self._sent.forget(key)
            raise
        match = _ITEM_ID.search(request["url"])
        new_id = created_id(result) if method == "POST" else (match.group(1) if match else "")
        with self._lock:
            self.learn(number, new_id)
        self._sent.accept(key, {"id": new_id})
        return f"{method} {result.status}" + ("" if new_id else "; the answer did not give the new id")

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

        Raises ``FmApiError``, ``AuthError`` or ``Unresolved`` naming the first request (in order) that failed, and ``Cancelled`` when the
        send is cancelled (the requests cut off are then logged as in doubt).
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
                    return f"{CANCELLED_PREFIX} after {sent} request(s)."
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
                if self._sent.done(key):
                    log.debug("BOM request %d of %s was sent before, skipped", index + 1, parent)
                    progress()
                    return False
                doubtful = self._sent.in_doubt(key)
                final = resolve(request, self._values(request))
            log.debug("BOM request %d of %s: %s %s", index + 1, parent, final["method"], final["url"])
            try:   # outside the lock, so the others go out at the same time
                with self._slots:
                    self._fm.send_json(final["method"], final["url"], final.get("body"))
            except Cancelled:
                self._sent.doubt(key, "was cancelled while it was being sent")
                raise
            except FmApiError as exc:
                if final["method"] == "POST" and DUPLICATE_LINE in str(exc):
                    log.info("BOM line already there, nothing to add: %s", final["url"])   # e.g. an earlier send added it
                elif doubtful and final["method"] == "DELETE" and exc.status == 404:
                    log.info("BOM line already gone, nothing to remove: %s", final["url"])   # the cancelled send removed it
                else:
                    if exc.outcome_unknown:   # a resend finds out whether it was done
                        self._sent.doubt(key, "got no answer or a server error")
                    raise
        except (FmApiError, AuthError, Unresolved) as exc:
            failed.set()
            log.warning("Sending the Bill of Materials of %s failed at request %d: %s", parent, index + 1, exc)
            if isinstance(exc, FmApiError):   # which request, and the status it was refused with
                raise FmApiError(f"Request {index + 1} of {count}: {exc}", exc.status) from exc
            raise
        self._sent.accept(key, {})
        progress()
        return True

    # ---- Ids -------------------------------------------------------------------------

    def _item_id(self, number: str) -> str:
        """Id of the item with this number (as ``key_of`` writes it): known from the folder or the send, else searched in Fusion Manage."""
        with self._lock:
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
        with self._lock:
            if item_id not in self._facts:
                data = as_dict(self._fm.get_json(f"/api/v3/workspaces/{self._workspace_id}/items/{item_id}"))
                tenant = _TENANT.search(str(data.get("urn", "")))
                self._facts[item_id] = {"tenant": tenant.group(1) if tenant else "", "version": str(data.get("version") or "")}
                log.info("Item %s: tenant %r, version %r", item_id, self._facts[item_id]["tenant"], self._facts[item_id]["version"])
            return self._facts[item_id]

    def _values(self, request: Dict[str, Any]) -> Dict[Key, str]:
        """The value of every marker in ``request`` (those left out make ``resolve`` say which are missing)."""
        values: Dict[Key, str] = {}
        found = markers(request)
        for kind, argument in found:
            if kind == ITEM:
                values[(kind, argument)] = self._item_id(argument)
            elif kind == VERSION:
                version = self._item_facts(self._item_id(argument))["version"]
                if version:
                    values[(kind, argument)] = version
        if key_of(TENANT) in found:   # the tenant is the same for every item: any item of the request tells it
            first = next((a for k, a in found if k == ITEM), "")
            tenant = self._item_facts(self._item_id(first))["tenant"] if first else ""
            if tenant:
                values[key_of(TENANT)] = tenant
        return values


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
        self._dispatcher = Dispatcher(path, fm.with_cancel(self.token), str(manifest.get("workspace_id") or ""),   # cancelling ends a request under way
                                      {number: str(info.get("id") or "") for number, info in manifest["items"].items()})
        self.rows = ([self.row(i["number"], "Create item" if i["request"]["method"] == "POST" else "Update item") for i in plan["items"]] +
                     [self.row(b["parent"], f"Bill of Materials, {len(b['requests'])} request(s)") for b in plan["boms"]])
        self.total = len(self.rows)

    # ---- Worker thread ----------------------------------------------------------

    def _steps(self) -> None:
        """Send every item, then the Bill of Materials of each parent: a step each (the items together, then the parents in the order of the rows)."""
        items = self.plan["items"]
        with ThreadPoolExecutor(max_workers=WRITES) as pool:   # the items go out together; the dispatcher keeps how many are in flight
            list(pool.map(lambda pair: self._send_item(*pair), zip(self.rows, items)))
        for row, job in zip(self.rows[len(items):], self.plan["boms"]):   # every item is sent before the first Bill of Materials
            if self.cancelled:
                break
            self._step(row, lambda: self._dispatcher.send_bom(job["parent"], job["requests"], lambda: self.cancelled))

    def _send_item(self, row: Dict[str, Any], job: Dict[str, Any]) -> None:
        """One item's send, on a pool thread (nothing once the run is cancelled)."""
        if not self.cancelled:
            self._step(row, lambda: self._dispatcher.send_item(job["number"], job["request"]))

    def _step(self, row: Dict[str, Any], action: Callable[[], str]) -> None:
        """One row's send: done, cancelled or an error with the reason. A cancel that cut a request off ends the whole send (``Cancelled``)."""
        row["status"] = RUNNING
        try:
            row["detail"] = action()
            row["status"] = CANCELLED if self.cancelled and was_cancelled(row["detail"]) else DONE
        except Cancelled:
            row["status"], row["detail"] = CANCELLED, CUT_OFF
            raise
        except (FmApiError, AuthError, Unresolved) as exc:
            row["status"], row["detail"] = ERROR, str(exc)
        with self._lock:
            self.done += 1

    def _finish(self, phase: str, message: str) -> None:
        self._end(phase, message)
        log.info("Send run %s %s: %s (%s)", self.id, phase, self.path, message or "ok")

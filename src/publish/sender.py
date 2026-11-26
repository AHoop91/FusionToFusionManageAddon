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

Layer: application (sequences the sends and keeps the log); the requests themselves are made by ``fm``.
"""

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..auth.errors import AuthError
from ..core.cancel import Cancelled
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list
from ..fm.client import FmApiError, FmClient, SendResult
from ..fm.refusal import refusal_text
from ..fm.v3_search import WORKING, ItemFinder
from .job_state import JobState
from .placeholders import ITEM, TENANT, VERSION, Key, Unresolved, key_of, markers, resolve
from .send_log import FolderError, SendLog
from .states import CANCELLED, DONE, ERROR, RUNNING

log = get_logger("publish_send")

DUPLICATE_LINE = "error.bom.duplicate"   # Fusion Manage's answer to adding an item the BOM already has
BOM_REQUESTS = 5   # Bill of Materials requests of one parent in flight at once
WRITES = 5   # requests that change Fusion Manage in flight at once, across items and every parent's Bill of Materials
_ITEM_ID = re.compile(r"/items/(\d+)")
_TENANT = re.compile(r"item:([^.]+)\.")


def cut_off_text() -> str:
    """The detail of a step a cancel ended while it was being sent."""
    return t("run.send_cut_off")


def was_cancelled(detail: str) -> bool:
    """Whether the detail ``send_bom`` gave says the cancel stopped it between requests: it is the text of ``send_bom`` for that, with the
    count filled in, so it is known by what comes before and after the count in the language in use."""
    before, _, after = t("run.send_bom_cancelled", sent="\x00").partition("\x00")
    return detail.startswith(before) and detail.endswith(after)


def _read(path: str) -> Any:
    """The JSON in a file of the folder. Raises ``FolderError`` when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise FolderError(t("run.send_file_unreadable", name=os.path.basename(path), error=exc)) from exc


def _in_folder(folder: str, relative: str) -> str:
    """The path of a file the manifest names, which has to be in the folder: what is read from it is sent to Fusion Manage."""
    root, path = os.path.realpath(folder), os.path.realpath(os.path.join(folder, relative))
    try:
        inside = os.path.commonpath([root, path]) == root
    except ValueError:   # another drive
        inside = False
    if not inside:
        raise FolderError(t("run.send_file_outside", name=relative))
    return path


def _request(name: str, data: Any) -> Dict[str, Any]:
    """A request read from a file, which has to have what a send uses: its method and its url."""
    if not isinstance(data, dict) or not isinstance(data.get("method"), str) or not isinstance(data.get("url"), str):
        raise FolderError(t("run.send_not_request", name=name))
    return data


def load_plan(path: str) -> Dict[str, Any]:
    """``{"manifest", "items": [{"number", "request"}], "boms": [{"parent", "requests"}]}`` read from a publish folder.

    Raises ``FolderError`` for a folder that is not one, was written by an older version, or holds a file that is not what it says."""
    if not os.path.isfile(os.path.join(path, "manifest.json")):
        raise FolderError(t("run.send_not_folder"))
    manifest = _read(os.path.join(path, "manifest.json"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), dict):
        raise FolderError(t("run.send_older_folder"))
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


FACT_READERS = 5   # items read at once for the versions a request names


class Dispatcher:
    """Sends item and Bill of Materials requests, remembering the ids of the items and what was accepted.

    Safe to call from several threads, which is how it is used: items and Bill of Materials requests go out together, at most ``WRITES`` at
    once. The lock is held only to look up and change ids, never while a request is made or the log is written: the log goes to disk
    before a send goes on, so a write made under the lock would hold up every other item. (It is re-entrant, and what changes the ids is
    taken with it.)
    """

    def __init__(self, path: str, fm: FmClient, workspace_id: str, known: Optional[Dict[str, str]] = None) -> None:
        self.path, self._fm, self._workspace_id = path, fm, workspace_id
        self._search = ItemFinder(fm, WORKING)
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
            raise FmApiError(t("run.send_created_unclear", item=shown, count=len(hits)))
        return hits[0]["id"] if hits else ""

    def _earlier_send(self, number: str, key: str) -> Tuple[str, bool]:
        """``(done, doubtful)``: ``done`` is what to report when an earlier send accepted the item ("" if it did not), ``doubtful`` whether an
        earlier send was cut off while sending it."""
        with self._lock:
            if self._sent.done(key):
                self.learn(number, str(self._sent.entry(key).get("id") or ""))
                return t("run.send_already_sent"), False
            return "", self._sent.in_doubt(key)

    def _adopt_created(self, number: str, key: str) -> bool:
        """Whether the create an earlier send was cut off in had made the item: if so it is learned and logged as accepted."""
        existing = self._created_before(number)
        if existing:
            self.learn(number, existing)
            self._sent.accept(key, {"id": existing})
        return bool(existing)

    def send_item(self, number: str, request: Dict[str, Any]) -> str:
        """Create or update one item; returns what was done. Raises ``FmApiError`` or ``AuthError`` when Fusion Manage refuses, and
        ``Cancelled`` when the send is cancelled (the item is then logged as in doubt)."""
        key, method = "item:" + number, request["method"]
        done, doubtful = self._earlier_send(number, key)
        if done:
            return done
        if doubtful and method == "POST" and self._adopt_created(number, key):   # an update can be sent again; a create may have made the item
            return t("run.send_already_created")
        intended = method == "POST" and not doubtful   # an entry of its own is logged first: a crash while the create is under way leaves it in doubt
        if intended:
            self._sent.intend(key)
        result = self._write_item(number, key, request, intended)
        match = _ITEM_ID.search(request["url"])
        new_id = created_id(result) if method == "POST" else (match.group(1) if match else "")
        self.learn(number, new_id)
        self._sent.accept(key, {"id": new_id})
        return f"{method} {result.status}" if new_id else t("run.send_no_new_id", method=method, status=result.status)

    def _write_item(self, number: str, key: str, request: Dict[str, Any], intended: bool) -> SendResult:
        """Make the request of an item, outside the lock so the items go out at the same time, and log what a failure means for a resend."""
        try:
            with self._slots:
                return self._fm.send_json(request["method"], request["url"], request.get("body"))
        except Cancelled:
            self._sent.doubt(key, "was cancelled while it was being sent")
            raise
        except (FmApiError, AuthError) as exc:
            log.warning("Sending item %s failed: %s", number, exc)
            if request["method"] == "POST":   # a failed update leaves the item there, so its Bill of Materials can still be changed
                with self._lock:
                    self._failed.add(number.casefold())
            if isinstance(exc, FmApiError) and exc.outcome_unknown:   # sent, perhaps, and done, perhaps: a resend finds out first
                self._sent.doubt(key, "got no answer or a server error")
            elif intended:   # refused for good: not done, so nothing to find out
                self._sent.forget(key)
            raise

    # ---- Bill of Materials -----------------------------------------------------------

    def send_bom(self, parent: str, requests: List[Dict[str, Any]], cancelled: Callable[[], bool] = lambda: False,
                 progress: Callable[[], None] = lambda: None) -> str:
        """Send the lines of one parent's Bill of Materials: removals, then changes to lines, then additions.

        Removals go out together, then the updates (quantities and renumbers, all ``PATCH``) together, then the additions together. Each step
        starts when the one before has finished, so a number is freed before another line takes it. A failure ends the step it is in, and nothing after it is sent. ``progress`` is called
        after each request, sent or found already sent.

        Raises ``FmApiError``, ``AuthError`` or ``Unresolved`` naming the first request (in order) that failed, and ``Cancelled`` when the
        send is cancelled (the requests cut off are then logged as in doubt).
        """
        with self._lock:
            if parent.casefold() in self._failed:
                raise FmApiError(t("run.send_parent_not_created", item=parent))
        indexed = list(enumerate(requests))
        steps = [[(i, r) for i, r in indexed if r["method"] == "DELETE"],
                 [(i, r) for i, r in indexed if r["method"] == "PATCH"],
                 [(i, r) for i, r in indexed if r["method"] not in ("DELETE", "PATCH")]]
        send = _BomSend(parent, len(requests), cancelled, progress)
        sent = 0
        for batch in steps:
            if batch:
                sent += self._send_batch(send, batch)
                if cancelled():
                    return t("run.send_bom_cancelled", sent=sent)
        return t("run.send_bom_sent", count=len(requests))

    def _send_batch(self, send: "_BomSend", batch: List[Tuple[int, Dict[str, Any]]]) -> int:
        """Send the requests of a batch, ``BOM_REQUESTS`` at a time, and return how many were sent. The first to fail is raised once the
        others in flight have finished; those not started by then are left unsent."""
        with ThreadPoolExecutor(max_workers=BOM_REQUESTS) as pool:
            sent = pool.map(lambda item: self._send_bom_request(send, item[0], item[1]), batch)
            return list(sent).count(True)

    def _send_bom_request(self, send: "_BomSend", index: int, request: Dict[str, Any]) -> bool:
        """One request of a Bill of Materials, on a pool thread: True when it was sent, False when it was skipped (sent before, cancelled, or another request has failed)."""
        if send.cancelled() or send.failed.is_set():
            return False
        key = f"bom:{send.parent}:{index}"
        try:
            with self._lock:   # the ids it needs may be searched for, once, and shared
                if self._sent.done(key):
                    send.progress()
                    return False
                doubtful = self._sent.in_doubt(key)
                final = resolve(request, self._values(request))
            self._write_line(key, final, doubtful)
        except (FmApiError, AuthError, Unresolved) as exc:
            send.failed.set()
            log.warning("Sending the Bill of Materials of %s failed at request %d: %s", send.parent, index + 1, exc)
            if isinstance(exc, FmApiError):   # which request, and the status it was refused with
                raise FmApiError(t("run.send_request_failed", number=index + 1, count=send.count, error=refusal_text(exc)), exc.status) from exc
            raise
        self._sent.accept(key, {})
        send.progress()
        return True

    def _write_line(self, key: str, final: Dict[str, Any], doubtful: bool) -> None:
        """Make one resolved request of a Bill of Materials, outside the lock so the others go out at the same time. A line that is
        already there (an add) or already gone (a remove the cancelled send made) is not an error."""
        try:
            with self._slots:
                self._fm.send_json(final["method"], final["url"], final.get("body"))
        except Cancelled:
            self._sent.doubt(key, "was cancelled while it was being sent")
            raise
        except FmApiError as exc:
            if _already_settled(final, exc, doubtful):
                return
            if exc.outcome_unknown:   # a resend finds out whether it was done
                self._sent.doubt(key, "got no answer or a server error")
            raise

    # ---- Ids -------------------------------------------------------------------------

    def _item_id(self, number: str) -> str:
        """Id of the item with this number (as ``key_of`` writes it): known from the folder or the send, else searched in Fusion Manage."""
        with self._lock:
            shown = self._shown.get(number, number)
            if number in self._failed:
                raise FmApiError(t("run.send_item_not_created", item=shown))
            if not self._ids.get(number):
                hits = self._search.search(self._workspace_id, shown)
                if len(hits) != 1:
                    raise FmApiError(t("run.send_item_missing", item=shown) if not hits else t("run.send_item_ambiguous", item=shown, count=len(hits)))
                self._ids[number] = hits[0]["id"]
            return self._ids[number]

    def _item_facts(self, item_id: str) -> Dict[str, str]:
        """Tenant code and revision of an item, read from the item itself. The read is made outside the lock: held across a request (about a second), it made
        every thread wait for each other's reads, so the items of a Bill of Materials were read one after another."""
        with self._lock:
            known = self._facts.get(item_id)
        if known is not None:
            return known
        data = as_dict(self._fm.get_json(f"/api/v3/workspaces/{self._workspace_id}/items/{item_id}"))
        tenant = _TENANT.search(str(data.get("urn", "")))
        facts = {"tenant": tenant.group(1) if tenant else "", "version": str(data.get("version") or "")}
        with self._lock:
            return self._facts.setdefault(item_id, facts)

    def _read_facts(self, item_ids: List[str]) -> None:
        """Read the items not read yet together (a request names the version of each item it holds), not one after another."""
        missing = [i for i in dict.fromkeys(item_ids) if i not in self._facts]
        if len(missing) > 1:
            with ThreadPoolExecutor(max_workers=min(len(missing), FACT_READERS)) as pool:
                list(pool.map(self._item_facts, missing))

    def _values(self, request: Dict[str, Any]) -> Dict[Key, str]:
        """The value of every marker in ``request`` (those left out make ``resolve`` say which are missing)."""
        values: Dict[Key, str] = {}
        found = markers(request)
        self._read_facts([self._item_id(argument) for kind, argument in found if kind == VERSION])
        for kind, argument in found:
            value = self._marker_value(kind, argument)
            if kind == ITEM or value:   # an item's id is kept even when empty; only a version the item lacks is left out
                values[(kind, argument)] = value
        if key_of(TENANT) in found:
            tenant = self._tenant_of(found)
            if tenant:
                values[key_of(TENANT)] = tenant
        return values

    def _marker_value(self, kind: str, argument: str) -> str:
        """The value of an ``{{item:...}}`` or ``{{version:...}}`` marker ("" for a version the item does not have, and for other kinds)."""
        if kind == ITEM:
            return self._item_id(argument)
        if kind == VERSION:
            return self._item_facts(self._item_id(argument))["version"]
        return ""

    def _tenant_of(self, found: Set[Key]) -> str:
        """The tenant code for a request's ``{{tenant}}``: the same for every item, so any item of the request tells it ("" if it holds none)."""
        first = next((a for k, a in found if k == ITEM), "")
        return self._item_facts(self._item_id(first))["tenant"] if first else ""


def _already_settled(final: Dict[str, Any], exc: FmApiError, doubtful: bool) -> bool:
    """Whether a refused Bill of Materials request has nothing left to do: the line is already there (an add), or already gone (a remove)."""
    if final["method"] == "POST" and DUPLICATE_LINE in str(exc):
        log.info("BOM line already there, nothing to add: %s", final["url"])   # e.g. an earlier send added it
        return True
    if doubtful and final["method"] == "DELETE" and exc.status == 404:
        log.info("BOM line already gone, nothing to remove: %s", final["url"])   # the cancelled send removed it
        return True
    return False


class _BomSend:
    """What the requests of one parent's Bill of Materials share while they are sent: the parent, how many there are, the cancel and progress
    callbacks, and the flag the first failure sets so the requests not yet started are left unsent."""

    def __init__(self, parent: str, count: int, cancelled: Callable[[], bool], progress: Callable[[], None]) -> None:
        self.parent, self.count, self.cancelled, self.progress = parent, count, cancelled, progress
        self.failed = threading.Event()


class SendRun(JobState):
    """State and steps of sending one folder. ``snapshot`` is what the panels poll."""

    kind = "send"
    sends = True
    stage = "sending"

    @property
    def unreached(self) -> str:
        return t("run.send_not_sent")

    def __init__(self, path: str, plan: Dict[str, Any], fm: FmClient) -> None:
        manifest = plan["manifest"]
        super().__init__(str(manifest.get("root") or os.path.basename(path)), path)
        self.plan = plan
        self._dispatcher = Dispatcher(path, fm.with_cancel(self.token), str(manifest.get("workspace_id") or ""),   # cancelling ends a request under way
                                      {number: str(info.get("id") or "") for number, info in manifest["items"].items()})
        self.rows = ([self.row(i["number"], t("run.send_create_item") if i["request"]["method"] == "POST" else t("run.send_update_item")) for i in plan["items"]] +
                     [self.row(b["parent"], t("run.bom_row", count=len(b["requests"]))) for b in plan["boms"]])
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
            self._send_parent(row, job)

    def _send_parent(self, row: Dict[str, Any], job: Dict[str, Any]) -> None:
        """One parent's Bill of Materials, as a step of its row."""
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
            row["status"], row["detail"] = CANCELLED, cut_off_text()
            raise
        except (FmApiError, AuthError, Unresolved) as exc:
            unknown = isinstance(exc, FmApiError) and exc.outcome_unknown   # no answer, or a server error: it may have been done
            row["status"], row["detail"] = ERROR, f"{exc} {t('run.send_outcome_unknown')}" if unknown else str(exc)
        with self._lock:
            self.done += 1

    def _finish(self, phase: str, message: str) -> None:
        """End the run and log how it ended."""
        self._end(phase, message)
        log.info("Send run %s %s: %s (%s)", self.id, phase, self.path, message or "ok")

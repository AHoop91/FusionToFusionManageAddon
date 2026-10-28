"""One publish run: write the requests and files of the items into a folder, and send them to Fusion Manage.

A run is a job in the ``JobQueue``. ``work`` runs on the queue's worker thread and does everything
that needs the network (Data Model and Fusion Manage reads, thumbnail downloads) and writes the
JSON; the items are prepared several at a time (their shared reads are in ``read_ahead``), and each is sent as soon as its request is written.
Once every item is done, the Bill of Materials of each parent is sent (``sender``). Nothing here
touches the Fusion API, so a run never blocks Fusion and does not need the design to stay open.
"""

import base64
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from ..auth.errors import AuthError
from ..config.workspace_models import KINDS_BY_ID, WorkspaceConfig
from ..core.logging_setup import get_logger
from ..fm.client import LOOKUPS, FmApiError, FmClient
from ..fm.components import ComponentService, manage_link
from ..fm.picklists import PicklistResolver
from ..fm.search_query import WORKING
from ..fm.sections import SectionService
from ..fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ..fusion_mfg.model_service import read_thumbnail_url
from ..sync.item_compare import compare_with_item, item_number_of, lookup_item
from ..sync.property_compare import FOUND, MISMATCH, NEW
from .bom_requests import bom_requests
from .download import download
from .item_requests import item_request
from .job_state import JobState
from .placeholders import Unresolved
from .read_ahead import ReadAhead, component_id_of
from .sender import Dispatcher
from .shared_numbers import shared_numbers, shared_reason
from .states import CANCELLED, DONE, ERROR, RUNNING
from .thumbnail import clear_white_background
from .writer import FAILED, OK, SKIPPED, PublishFolder, safe_name

log = get_logger("publish")

WORKERS = 5   # items prepared at once
SENT = "sent to Fusion Manage"   # the artifact of an item that was sent

SKIPPED_COUNT = "skipped"   # the job's ``counts`` key for the items left out on purpose


class SharedItemNumbers(Exception):
    """Item numbers that several Fusion Manage items carry: the run cannot tell which item each means, and must not guess."""

    def __init__(self, counts: Dict[str, int]) -> None:
        self.counts = counts   # item number -> how many Fusion Manage items carry it
        super().__init__("Nothing was published. Renumber or remove the extra items in Fusion Manage, then publish again.")


class PublishRun(JobState):
    """State and steps of one run. ``snapshot`` is what the panel polls."""

    kind = "publish"
    stage = "validating"   # then "items", then "bom": the run looks up every item number before it writes anything
    unreached = "Not published: the run failed."

    def __init__(self, folder: PublishFolder, job: Dict[str, Any], cfg: WorkspaceConfig, client: FusionGraphQlClient,
                 fm: FmClient, model_id: str, time: str, send: bool = False) -> None:
        super().__init__(str(job.get("root_number") or "design"), folder.path)
        self.folder, self.job, self.cfg = folder, job, cfg
        self.sends = send   # send each item as it is written, then the Bill of Materials
        self._dispatcher = Dispatcher(folder.path, fm, cfg.workspace_id) if send else None
        self._client, self._fm, self._model_id, self._time = client, fm, model_id, time
        self.total = len(job["items"])
        self.rows = [self.row(item_number_of(i), str(i.get("description") or i.get("name") or ""), bool(i.get("root"))) for i in job["items"]]
        self._row_of = {id(i): row for i, row in zip(job["items"], self.rows)}
        self._bom_requests = bom_requests(cfg.workspace_id, job["operations"])
        # A Bill of Materials is sent after the items, so its rows come last and are not counted in the items processed.
        self._bom_row_of = {parent: self.row(parent, f"Bill of Materials, {len(lines)} request(s)")
                            for parent, lines in self._bom_requests.items()} if send else {}
        self.rows.extend(self._bom_row_of.values())
        self._bom_total = sum(len(lines) for lines in self._bom_requests.values()) if send else 0   # requests, not parents: one parent can have many
        self._bom_done = 0   # requests sent or found sent already, so far
        self._field_sections: Dict[str, str] = {}   # FM field id -> section link, read once per run
        self._physical = cfg.maps_physical()   # read them only when something maps them
        self._picklists = PicklistResolver(self._fm, cfg.workspace_id)   # options of the picklist fields, read once per run
        self._shared = shared_numbers(job["items"], job["summary"])   # item number -> the components that carry it: none of them is published
        self._ahead: Optional[ReadAhead] = None   # the reads the items share, while the run is on them
        self._skipped = 0   # items left out on purpose, so the progress dialog does not count them as published

    @property
    def unlisted(self) -> bool:
        """A run that failed in its validation wrote nothing: there is nothing in the Job Queue to look at, retry or clear."""
        return self.phase == ERROR and self.stage == "validating"

    # ---- Worker thread ----------------------------------------------------------

    def work(self) -> None:
        if not self._start():   # cancelled while it waited
            return
        started = time.monotonic()
        try:
            if self.cfg.workspace_id:
                self._field_sections = SectionService(self._fm).field_sections(self.cfg.workspace_id)
            publishable = [i for i in self.job["items"] if item_number_of(i).lower() not in self._shared]
            with ReadAhead(publishable, self.job["summary"], self._client, self._fm, self.cfg.workspace_id, self._time,
                           self._physical, lambda: self.cancelled) as self._ahead, ThreadPoolExecutor(max_workers=WORKERS) as pool:
                self._require_unique_numbers(publishable)   # before the first item is written
                self._set(stage="items")
                list(pool.map(self._prepare, self.job["items"]))
            if not self.cancelled:
                self._write_boms()
            log.info("Prepared %d item(s) in %.1fs", len(self.job["items"]), time.monotonic() - started)
            if self.sends and not self.cancelled:
                self._send_boms()   # only now: every item has been created or updated
        except SharedItemNumbers as exc:
            log.warning("Publish stopped before writing: %s", ", ".join(sorted(exc.counts)))
            self._finish(ERROR, str(exc))
            return
        except Exception as exc:
            log.exception("Publish run failed")
            self._finish(ERROR, str(exc) or type(exc).__name__)
            return
        self._finish(CANCELLED if self.cancelled else DONE, "Cancelled." if self.cancelled else "")

    def _require_unique_numbers(self, items: List[Dict[str, Any]]) -> None:
        """Fail the whole run, with nothing written, when an item number is carried by several Fusion Manage items. A search that fails fails the run too:
        without it the numbers cannot be known to be unique."""
        counts = {number: len(self._ahead.found(number) or []) for number in {item_number_of(i) for i in items}}
        shared = {number: count for number, count in counts.items() if count > 1}
        if shared:
            raise SharedItemNumbers(shared)

    def snapshot(self) -> Dict[str, Any]:
        """The job's state, with the validation: how far the look-up of the item numbers has come, and how many items carry each number found."""
        ahead = self._ahead
        with self._lock:
            sent = self._bom_done
        return {**super().snapshot(), "validation": {"done": ahead.searched if ahead else 0, "total": ahead.to_search if ahead else 0,
                                                     "counts": ahead.hits() if ahead else {}},
                "bom": {"done": sent, "total": self._bom_total}}

    def _counts(self) -> Dict[str, int]:
        return {SKIPPED_COUNT: self._skipped}

    def _leave_out(self, row: Dict[str, Any], detail: str) -> None:
        """An item that is done without anything being done for it."""
        row["status"], row["detail"] = DONE, detail
        with self._lock:
            self._skipped += 1
            self.done += 1

    def _send_boms(self) -> None:
        """Send the Bill of Materials of each parent, several parents at a time; a failure stops that parent only."""
        self._set(stage="bom")
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(lambda parent: self._send_bom(*parent), self._bom_requests.items()))

    def _send_bom(self, parent: str, lines: List[Dict[str, Any]]) -> None:
        """One parent's Bill of Materials, on a pool thread: the others go on if it fails."""
        if self.cancelled:
            return
        row = self._bom_row_of[parent]
        row["status"] = RUNNING
        sent = [0]

        def progress() -> None:
            sent[0] += 1
            row["detail"] = f"{sent[0]} of {len(lines)} request(s) sent."
            with self._lock:
                self._bom_done += 1

        try:
            row["detail"] = self._dispatcher.send_bom(parent, lines, lambda: self.cancelled, progress)
            row["status"] = CANCELLED if row["detail"].startswith("Cancelled") else DONE
        except (FmApiError, AuthError, Unresolved) as exc:
            row["status"], row["detail"] = ERROR, str(exc)
            self.folder.record(parent, SENT, FAILED, str(exc))

    def _prepare(self, item: Dict[str, Any]) -> None:
        """One item, on a pool thread; a failure here never stops the others."""
        if self.cancelled:
            return
        number = item_number_of(item)
        row = self._row_of[id(item)]
        # The panel leaves out what has no item number or shares one; this keeps a job that has them anyway from sending an empty
        # number, or from writing one item from several components.
        if not number:
            return self._leave_out(row, "Skipped: no item number.")
        if number.lower() in self._shared:
            reason = shared_reason(number, self._shared[number.lower()])
            self.folder.record(number, "item", SKIPPED, reason)
            return self._leave_out(row, reason)
        row["status"] = RUNNING
        unresolved = False
        try:
            unresolved = self._item(item, number)
        except Exception as exc:
            log.exception("Publishing %s failed", number)
            self.folder.record(number, "item", FAILED, str(exc) or type(exc).__name__)
        entries = self.folder.entries_of(number)
        row["detail"] = "; ".join(f"{e['artifact']}: {e['detail']}" for e in entries)
        with self._lock:
            row["status"] = ERROR if any(e["status"] == FAILED for e in entries) else DONE
            self.done += 1
            self._skipped += unresolved

    def _item(self, item: Dict[str, Any], number: str) -> bool:
        """Prepare, and with ``sends`` send, one item. True when Fusion Manage could not say which item it is, so nothing was done for it."""
        folder = self.folder.item_dir(number)
        began = time.monotonic()
        summary = self.job["summary"]
        component_id = component_id_of(item, summary)
        component = summary if item.get("root") else {k: item.get(k, "") for k in ("id", "item_number", "part_number", "description")}
        # Fusion Manage is asked for the item while the Data Model request this item shares is on its way.
        with ThreadPoolExecutor(max_workers=1) as background:
            pending = background.submit(lookup_item, component, self.cfg, self._fm, self._ahead.found(number), WORKING)
            read = self._ahead.read(component_id)
            lookup = pending.result()
        result = compare_with_item(read["properties"], component, self.cfg, lookup, self._picklists.fit_number,
                                   with_values=True, convert_unit=self._picklists.convert_unit)
        link = self._component(number, result["fm"], read["link"])
        rows = self._option_rows(number, result["rows"])
        self._record_blank(number, rows)
        request, reason = self._request(number, folder, component_id, read["thumbnail_url"], result, rows, link)
        request_file = self._write_request(number, folder, request, reason)
        state = self.folder.items[number] = {"id": str(result["fm"].get("item_id") or ""), "state": str(result["fm"].get("state") or ""),
                                             "request": request_file}
        if self._dispatcher:
            self._dispatcher.learn(number, state["id"])
            if request is not None:
                self._send_item(number, request)
        log.debug("Item %s: Fusion Manage is %s (id %s); request: %s", number, state["state"] or "unknown", state["id"] or "none",
                  reason if request is None else request["method"] + " " + request["url"])
        log.info("Prepared %s in %.1fs", number, time.monotonic() - began)
        return request is None and state["state"] != FOUND

    def _request(self, number: str, folder: str, component_id: str, thumbnail_url: str, result: Dict[str, Any],
                 rows: List[Dict[str, Any]], link: Optional[Tuple[str, str]]) -> Tuple[Optional[Dict[str, Any]], str]:
        """``(request, reason)`` of the item (see ``item_request``). A thumbnail goes along with a request only, so one is fetched
        only for an item that sends something."""
        def build(files: List[Tuple[str, Any]]) -> Tuple[Optional[Dict[str, Any]], str]:
            return item_request(self.cfg.workspace_id, result["fm"], rows, self.cfg.static_values, self._field_sections, files,
                                result["values"], link)   # the values tell which static values an existing item lacks

        request, reason = build([])
        if request is None:
            self.folder.record(number, "thumbnail", SKIPPED, "Not needed: nothing is sent for this item.")
            return request, reason
        image = self._thumbnail(number, folder, component_id, thumbnail_url)
        files = [(m.fm_field_id, image) for m in self.cfg.mappings if m.source == "thumbnail" and m.fm_field_id and image]
        return build(files) if files else (request, reason)

    def _record_blank(self, number: str, rows: List[Dict[str, Any]]) -> None:
        blank = [f"{r['name']} (-> {r['fm_field']})" for r in rows if r["fm_field"] and r["status"] == NEW and r["value"] == ""]
        if blank:
            self.folder.record(number, "blank fields", SKIPPED, "No value in the Data Model, not sent: " + ", ".join(blank))

    def _write_request(self, number: str, folder: str, request: Optional[Dict[str, Any]], reason: str) -> str:
        """Write the request to the item's folder and return its path ("" when there is none, and the reason is recorded)."""
        if request is None:
            self.folder.record(number, "item request", SKIPPED, reason)
            return ""
        path = os.path.join(folder, "item.request.json")
        self.folder.record(number, "item request", OK, request["method"] + " " + request["url"], self.folder.write_json(path, request))
        return path

    def _option_rows(self, number: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The rows with the text of each picklist field's value replaced by the link of its option.

        Fusion Manage refuses the whole item for text where a picklist wants an option, so a value that
        matches no option is left out and recorded.
        """
        out = []
        for row in rows:
            value = row["value"]
            if row["status"] not in (NEW, MISMATCH) or not row.get("fm_field") or not isinstance(value, str) or value == "" or value.startswith(LOOKUPS + "/"):
                out.append(row)
                continue
            link = self._picklists.link(row["fm_field"], value)
            if link is None:   # not a picklist field: a number is rounded to the digits the field takes
                fitted = self._picklists.fit_number(row["fm_field"], value)
                out.append(dict(row, value=fitted) if fitted != value else row)
            elif link:
                out.append(dict(row, value=link))
            else:
                self.folder.record(number, "picklist " + row["fm_field"], SKIPPED, f"'{value}' is not an option of {row['fm_field']} in Fusion Manage, so it was not sent.")
        return out

    def _component(self, number: str, fm_info: Dict[str, Any], linked: Dict[str, str]) -> Optional[Tuple[str, str]]:
        """``(field id, link)`` of the Components item for this part, or None (and the reason recorded) when it cannot be found.

        ``linked`` is the link the Data Model gave on the component's Item Number in Fusion (``urn`` and ``url``, empty when it is not linked)."""
        field_id = self.cfg.component_field
        if not field_id or fm_info.get("state") not in (FOUND, NEW):
            return None
        link = manage_link(linked["urn"], linked["url"])
        log.debug("Data Model link of %s: urn %r, url %r -> %s", number, linked["urn"], linked["url"], link or "none")
        reason = ""
        if not link:   # not linked in the Data Model: look for it in the component picklist
            try:
                link, reason = ComponentService(self._fm).find(KINDS_BY_ID["items"].component_lookup, number)
            except (FmApiError, AuthError) as exc:
                link, reason = "", str(exc)
        if not link:
            self.folder.record(number, "component link", FAILED, reason)
            return None
        self.folder.record(number, "component link", OK, f"{field_id} -> {link}")
        return field_id, link

    def _send_item(self, number: str, request: Dict[str, Any]) -> None:
        try:
            self.folder.record(number, SENT, OK, self._dispatcher.send_item(number, request))
        except (FmApiError, AuthError) as exc:
            self.folder.record(number, SENT, FAILED, str(exc))

    def _download_thumbnail(self, component_id: str, url: str) -> bytes:
        """The thumbnail at ``url``. The signed url expires soon and an item may wait for its turn, so when it will no longer serve, a fresh one is asked for."""
        try:
            return download(url)
        except Exception as exc:
            log.info("The thumbnail url of component %s would not serve (%s); asking for a fresh one", component_id, exc)
            fresh = read_thumbnail_url(self._client, self.job["summary"], component_id, self._time)
            if not fresh:
                raise
            return download(fresh)

    def _thumbnail(self, number: str, folder: str, component_id: str, url: str) -> str:
        """Download and save the thumbnail at ``url`` and return it as a ``data:image/png;base64,...`` value for an image field
        ("" if none). The saved file is the original; the value has its white background cleared."""
        try:
            if not url:
                self.folder.record(number, "thumbnail", SKIPPED, "The Data Model has no thumbnail for this component yet.")
                return ""
            data = self._download_thumbnail(component_id, url)
            self.folder.record(number, "thumbnail", OK, f"{len(data)} bytes",
                               self.folder.write_bytes(os.path.join(folder, "thumbnail.png"), data))
            return "data:image/png;base64," + base64.b64encode(clear_white_background(data)).decode("ascii")
        except Exception as exc:
            log.warning("Thumbnail of %s failed: %s", number, exc)
            self.folder.record(number, "thumbnail", FAILED, str(exc) or type(exc).__name__)
            return ""

    def _write_boms(self) -> None:
        for parent, lines in self._bom_requests.items():
            relative = os.path.join("bom", safe_name(parent) + ".bom.request.json")
            self.folder.record(parent, "bom requests", OK, f"{len(lines)} request(s)",
                               self.folder.write_json(relative, {"parent": parent, "requests": lines}))
        if not self._bom_requests:
            self.folder.record(self.job.get("root_number", ""), "bom requests", SKIPPED, "No Bill of Materials changes.")

    # ---- Any thread -------------------------------------------------------------

    def _save_manifest(self, message: str) -> None:
        self.folder.save_manifest({"root": self.job.get("root_number", ""), "workspace_id": self.cfg.workspace_id, "tenant": self._fm.tenant,
                                   "model": f"{self._model_id}|{self._time}", "cancelled": self.cancelled, "message": message})

    def _finish(self, phase: str, message: str) -> None:
        self._save_manifest(message)
        self._end(phase, message)
        log.info("Publish run %s %s: %s (%s)", self.id, phase, self.folder.path, message or "ok")

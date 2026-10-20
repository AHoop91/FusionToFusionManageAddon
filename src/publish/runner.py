"""One publish run: write the requests and files of the items into a folder, and send them to Fusion Manage.

A run is a job in the ``JobQueue``. ``work`` runs on the queue's worker thread and does everything
that needs the network (Data Model and Fusion Manage reads, thumbnail downloads) and writes the
JSON; the items are prepared several at a time, and each is sent as soon as its request is written.
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
from ..fm.sections import SectionService
from ..fusion_mfg.graphql_client import MfgGraphQlClient
from ..fusion_mfg.model_service import read_manage_item, read_section, read_thumbnail_url
from ..sync.item_compare import compare_with_item, item_number_of, lookup_item
from ..sync.property_compare import FOUND, MISMATCH, NEW
from .bom_requests import bom_requests
from .download import download
from .item_requests import item_request
from .placeholders import Unresolved
from .sender import Dispatcher
from .job_state import JobState
from .states import CANCELLED, DONE, ERROR, RUNNING
from .writer import FAILED, OK, SKIPPED, PublishFolder, safe_name

log = get_logger("publish")

WORKERS = 5   # items prepared at once
SENT = "sent to Fusion Manage"   # the artifact of an item that was sent


class PublishRun(JobState):
    """State and steps of one run. ``snapshot`` is what the panel polls."""

    kind = "publish"
    unreached = "Not published: the run failed."

    def __init__(self, folder: PublishFolder, job: Dict[str, Any], cfg: WorkspaceConfig, client: MfgGraphQlClient,
                 fm: FmClient, model_id: str, time: str, send: bool = False) -> None:
        super().__init__(str(job.get("root_number") or "design"), folder.path)
        self.folder, self.job, self.cfg = folder, job, cfg
        self.sends = send   # send each item as it is written, then the Bill of Materials
        self.stage = "items"   # items -> bom (only when ``sends``)
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
        self._field_sections: Dict[str, str] = {}   # FM field id -> section link, read once per run
        self._physical = cfg.maps_physical()   # read them only when something maps them
        self._picklists = PicklistResolver(self._fm, cfg.workspace_id)   # options of the picklist fields, read once per run

    # ---- Worker thread ----------------------------------------------------------

    def work(self) -> None:
        if not self._start():   # cancelled while it waited
            return
        started = time.monotonic()
        try:
            if self.cfg.workspace_id:
                self._field_sections = SectionService(self._fm).field_sections(self.cfg.workspace_id)
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                list(pool.map(self._prepare, self.job["items"]))
            if not self.cancelled:
                self._bom()
            log.info("Prepared %d item(s) in %.1fs", len(self.job["items"]), time.monotonic() - started)
            if self.sends and not self.cancelled:
                self._send_boms()   # only now: every item has been created or updated
        except Exception as exc:
            log.exception("Publish run failed")
            self._finish(ERROR, str(exc) or type(exc).__name__)
            return
        self._finish(CANCELLED if self.cancelled else DONE, "Cancelled." if self.cancelled else "")

    def _send_boms(self) -> None:
        """Send the Bill of Materials of each parent, one after the other; a failure stops that parent only."""
        self._set(stage="bom")
        for parent, lines in self._bom_requests.items():
            if self.cancelled:
                break
            row = self._bom_row_of[parent]
            self._set(current=parent)
            row["status"] = RUNNING
            try:
                row["detail"] = self._dispatcher.send_bom(parent, lines, lambda: self.cancelled)
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
        self._set(current=number)
        row["status"] = RUNNING
        try:
            self._item(item, number)
        except Exception as exc:
            log.exception("Publishing %s failed", number)
            self.folder.record(number, "item", FAILED, str(exc) or type(exc).__name__)
        entries = [e for e in list(self.folder.entries) if e["item"] == number]
        row["detail"] = "; ".join(f"{e['artifact']}: {e['detail']}" for e in entries)
        with self._lock:
            row["status"] = ERROR if any(e["status"] == FAILED for e in entries) else DONE
            self.done += 1

    def _item(self, item: Dict[str, Any], number: str) -> None:
        folder = self.folder.item_dir(number)
        summary = self.job["summary"]
        root = bool(item.get("root"))
        began = time.monotonic()
        if root:
            properties = read_section(self._client, "properties", self._model_id, self._time, summary, physical=self._physical)
            component = summary
        else:
            properties = read_section(self._client, "component", self._model_id, self._time, summary, item["id"], self._physical)["properties"]
            component = {k: item.get(k, "") for k in ("id", "item_number", "part_number", "description")}
        read_time = time.monotonic() - began

        component_id = str(summary.get("component_id") or "") if root else str(item["id"])
        image = self._thumbnail(number, folder, component_id)
        files = [(m.fm_field_id, image) for m in self.cfg.mappings if m.source == "thumbnail" and m.fm_field_id and image]

        result = compare_with_item(properties, component, self.cfg,
                                   lookup_item(component, self.cfg, self._fm, str(item.get("fm_item") or "")),
                                   self._picklists.fit_number, with_values=True, convert_unit=self._picklists.convert_unit)
        compare_time = time.monotonic() - began - read_time
        link = self._component(number, component_id, result["fm"])
        rows = self._option_rows(number, result["rows"])
        request, reason = item_request(self.cfg.workspace_id, result["fm"], rows, self.cfg.static_values,
                                       self._field_sections, files, result["values"], link)   # the values tell which static values an existing item lacks
        blank = [f"{r['name']} (-> {r['fm_field']})" for r in rows
                 if r["fm_field"] and r["status"] == NEW and r["value"] == ""]
        if blank:
            self.folder.record(number, "blank fields", SKIPPED, "No value in the Data Model, not sent: " + ", ".join(blank))
        request_file = ""
        if request is None:
            self.folder.record(number, "item request", SKIPPED, reason)
        else:
            request_file = os.path.join(folder, "item.request.json")
            self.folder.record(number, "item request", OK, request["method"] + " " + request["url"],
                               self.folder.write_json(request_file, request))
        self.folder.items[number] = {"id": str(result["fm"].get("item_id") or ""), "state": str(result["fm"].get("state") or ""),
                                     "request": request_file}
        if self._dispatcher:
            self._dispatcher.learn(number, self.folder.items[number]["id"])
            if request is not None:
                self._send_item(number, request)

        log.debug("Item %s: Fusion Manage is %s (id %s); request: %s", number, self.folder.items[number]["state"] or "unknown",
                  self.folder.items[number]["id"] or "none", reason if request is None else request["method"] + " " + request["url"])
        log.info("Prepared %s in %.1fs (Data Model %.1fs, Fusion Manage %.1fs)", number,
                 time.monotonic() - began, read_time, compare_time)

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

    def _manage_link(self, number: str, component_id: str) -> str:
        """The API link of the Fusion Manage item the Data Model says this component is linked to ("" if it says none)."""
        found = read_manage_item(self._client, self.job["summary"], component_id, self._time)
        link = manage_link(found["urn"], found["url"])
        log.info("Data Model link of %s: urn %r, url %r -> %s", number, found["urn"], found["url"], link or "none")
        return link

    def _component(self, number: str, component_id: str, fm_info: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """``(field id, link)`` of the Components item for this part, or None (and the reason recorded) when it cannot be found."""
        field_id = self.cfg.component_field
        if not field_id or fm_info.get("state") not in (FOUND, NEW):
            return None
        try:
            link = self._manage_link(number, component_id)   # the link on the component's Item Number in Fusion
        except Exception as exc:   # a failed read is not the same as "not linked": say so, do not guess from the picklist
            log.warning("The Data Model would not give the Fusion Manage link of %s: %s", number, exc)
            self.folder.record(number, "component link", FAILED, f"The Data Model would not give the link: {exc}")
            return None
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

    def _thumbnail(self, number: str, folder: str, component_id: str) -> str:
        """Save the thumbnail and return it as a ``data:image/png;base64,...`` value for an image field ("" if none).

        The signed url expires soon and the run may have waited in the queue, so a fresh one is asked for now."""
        try:
            url = read_thumbnail_url(self._client, self.job["summary"], component_id, self._time)
            if not url:
                self.folder.record(number, "thumbnail", SKIPPED, "The Data Model has no thumbnail for this component yet.")
                return ""
            data = download(url)
            self.folder.record(number, "thumbnail", OK, f"{len(data)} bytes",
                               self.folder.write_bytes(os.path.join(folder, "thumbnail.png"), data))
            return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        except Exception as exc:
            log.warning("Thumbnail of %s failed: %s", number, exc)
            self.folder.record(number, "thumbnail", FAILED, str(exc) or type(exc).__name__)
            return ""

    def _bom(self) -> None:
        requests = self._bom_requests
        for parent, items in requests.items():
            relative = os.path.join("bom", safe_name(parent) + ".bom.request.json")
            self.folder.record(parent, "bom requests", OK, f"{len(items)} request(s)",
                               self.folder.write_json(relative, {"parent": parent, "requests": items}))
        if not requests:
            self.folder.record(self.job.get("root_number", ""), "bom requests", SKIPPED, "No Bill of Materials changes.")

    # ---- Any thread -------------------------------------------------------------

    def _save_manifest(self, message: str) -> None:
        self.folder.save_manifest({"root": self.job.get("root_number", ""), "workspace_id": self.cfg.workspace_id, "tenant": self._fm.tenant,
                                   "model": f"{self._model_id}|{self._time}", "cancelled": self.cancelled, "message": message})

    def _finish(self, phase: str, message: str) -> None:
        self._save_manifest(message)
        self._end(phase, message)
        log.info("Publish run %s %s: %s (%s)", self.id, phase, self.folder.path, message or "ok")

"""One publish run: write the requests and files of the items into a folder, and send them to Fusion Manage.

A run is a job in the ``JobQueue``. ``work`` runs on the queue's worker thread and does everything
that needs the network (Data Model and Fusion Manage reads, thumbnail downloads) and writes the
JSON; the items are prepared several at a time, and each is sent as soon as its request is written.
Once every item is done, the Bill of Materials of each parent is sent (``sender``). Nothing here
touches the Fusion API, so a run never blocks Fusion and does not need the design to stay open.
"""

import base64
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from ..auth.errors import AuthError
from ..config.workspace_models import WorkspaceConfig
from ..core.logging_setup import get_logger
from ..fm.client import FmApiError, FmClient
from ..fm.items import ItemService
from ..fm.sections import SectionService
from ..fusion_mfg.graphql_client import MfgGraphQlClient
from ..fusion_mfg.model_service import read_section, read_thumbnail_url
from ..sync.item_compare import compare_item
from ..sync.property_compare import FOUND, NEW
from .bom_requests import bom_requests
from .download import download
from .item_requests import item_request
from .placeholders import Unresolved
from .sender import Dispatcher
from .states import CANCELLED, DONE, ERROR, FINISHED, QUEUED, RUNNING, time_now  # noqa: F401 - the states are also imported from here
from .writer import FAILED, OK, SKIPPED, PublishFolder, safe_name

log = get_logger("publish")

WORKERS = 5   # items prepared at once
SENT = "sent to Fusion Manage"   # the artifact of an item that was sent


class PublishRun:
    """State and steps of one run. ``snapshot`` is what the panel polls."""

    kind = "publish"

    def __init__(self, folder: PublishFolder, job: Dict[str, Any], cfg: WorkspaceConfig, client: MfgGraphQlClient,
                 fm: FmClient, model_id: str, time: str, send: bool = False) -> None:
        self.folder, self.job, self.cfg = folder, job, cfg
        self.sends = send   # send each item as it is written, then the Bill of Materials
        self.stage = "items"   # items -> bom (only when ``sends``)
        self._dispatcher = Dispatcher(folder.path, fm, cfg.workspace_id) if send else None
        self._client, self._fm, self._model_id, self._time = client, fm, model_id, time
        self.id = uuid.uuid4().hex[:8]
        self._lock = threading.Lock()
        self.name = str(job.get("root_number") or "design")
        self.phase = QUEUED   # queued -> running -> done | error; a queued run can be cancelled
        self.cancelled = False
        self.message = ""
        self.current = ""
        self.done = 0
        self.total = len(job["items"])
        # One row per item, for the Jobs window: queued -> running -> done | error | cancelled
        self.rows: List[Dict[str, Any]] = [
            {"item": _number(i), "description": str(i.get("description") or i.get("name") or ""), "root": bool(i.get("root")),
             "status": QUEUED, "detail": ""} for i in job["items"]]
        self._row_of = {id(i): row for i, row in zip(job["items"], self.rows)}
        self._bom_requests = bom_requests(cfg.workspace_id, job["operations"])
        # A Bill of Materials is sent after the items, so its rows come last and are not counted in the items processed.
        self._bom_row_of = {parent: {"item": parent, "description": f"Bill of Materials, {len(lines)} request(s)", "root": False,
                                     "status": QUEUED, "detail": ""} for parent, lines in self._bom_requests.items()} if send else {}
        self.rows.extend(self._bom_row_of.values())
        self._field_sections: Dict[str, str] = {}   # FM field id -> section link, read once per run
        self.queued_at = time_now()
        self.started_at = 0.0
        self.finished_at = 0.0

    # ---- Worker thread ----------------------------------------------------------

    def work(self) -> None:
        with self._lock:
            if self.phase != QUEUED:   # cancelled while it waited
                return
            self.phase = RUNNING
            self.started_at = time_now()
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
        number = _number(item)
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
            properties = read_section(self._client, "properties", self._model_id, self._time, summary)
            component = summary
        else:
            properties = read_section(self._client, "component", self._model_id, self._time, summary, item["id"])["properties"]
            component = {k: item.get(k, "") for k in ("id", "item_number", "part_number", "description")}
        read_time = time.monotonic() - began

        stored = str(summary.get("thumbnail") if root else item.get("thumbnail") or "")
        image = self._thumbnail(number, folder, str(summary.get("component_id") or "") if root else str(item["id"]), stored)
        files = [(m.fm_field_id, image) for m in self.cfg.mappings if m.source == "thumbnail" and m.fm_field_id and image]

        result = compare_item(properties, component, self.cfg, self._fm, str(item.get("fm_item") or ""))
        compare_time = time.monotonic() - began - read_time
        current = None   # what an existing item holds now, to tell which static values it lacks
        if result["fm"].get("state") == FOUND and result["fm"].get("item_id") and any(s.fm_field_id for s in self.cfg.static_values):
            current = ItemService(self._fm).read_values(self.cfg.workspace_id, result["fm"]["item_id"])
        request, reason = item_request(self.cfg.workspace_id, result["fm"], result["rows"], self.cfg.static_values,
                                       self._field_sections, files, current)
        blank = [f"{r['name']} (-> {r['fm_field']})" for r in result["rows"]
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

        log.info("Prepared %s in %.1fs (Data Model %.1fs, Fusion Manage %.1fs)", number,
                 time.monotonic() - began, read_time, compare_time)

    def _send_item(self, number: str, request: Dict[str, Any]) -> None:
        try:
            self.folder.record(number, SENT, OK, self._dispatcher.send_item(number, request))
        except (FmApiError, AuthError) as exc:
            self.folder.record(number, SENT, FAILED, str(exc))

    def _thumbnail(self, number: str, folder: str, component_id: str, stored_url: str) -> str:
        """Save the thumbnail and return it as a ``data:image/png;base64,...`` value for an image field ("" if none).

        The signed url expires soon and the run may have waited in the queue, so ask for a fresh one now."""
        url = stored_url
        try:
            url = read_thumbnail_url(self._client, self.job["summary"], component_id, self._time) or stored_url
        except Exception as exc:   # the url from when the panel loaded may still work
            log.warning("Fresh thumbnail address of %s failed, using the loaded one: %s", number, exc)
        if not url:
            self.folder.record(number, "thumbnail", SKIPPED, "The Data Model has no thumbnail for this component yet.")
            return ""
        try:
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

    def cancel(self) -> None:
        """Stop: a waiting run never starts, a running one stops after the items being read now."""
        with self._lock:
            self.cancelled = True
            waiting = self.phase == QUEUED
        if waiting:
            self._finish(CANCELLED, "Cancelled.")

    def _set(self, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(self, name, value)

    def _save_manifest(self, message: str) -> None:
        self.folder.save_manifest({"root": self.job.get("root_number", ""), "workspace_id": self.cfg.workspace_id, "tenant": self._fm.tenant,
                                   "model": f"{self._model_id}|{self._time}", "cancelled": self.cancelled, "message": message})

    def _finish(self, phase: str, message: str) -> None:
        self._save_manifest(message)
        with self._lock:
            for row in self.rows:
                if row["status"] == QUEUED:   # never reached: cancelled, or the run failed first
                    row["status"], row["detail"] = CANCELLED, "Cancelled." if self.cancelled else "Not published: the run failed."
        self._set(phase=phase, message=message, current="", finished_at=time_now())
        log.info("Publish run %s %s: %s (%s)", self.id, phase, self.folder.path, message or "ok")

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            entries = list(self.folder.entries)
            counts: Dict[str, int] = {}
            for entry in entries:
                counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            return {"id": self.id, "kind": self.kind, "name": self.name, "phase": self.phase, "message": self.message, "current": self.current,
                    "done": self.done, "total": self.total, "queued_at": self.queued_at, "started_at": self.started_at,
                    "finished_at": self.finished_at, "folder": self.folder.path, "counts": counts,
                    "sends": self.sends, "stage": self.stage, "rows": [dict(r) for r in self.rows]}


def _number(item: Dict[str, Any]) -> str:
    return str(item.get("item_number") or item.get("part_number") or "")

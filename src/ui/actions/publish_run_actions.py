"""Palette actions for publishing: queue the run, retry a failed one, and list, cancel and open the runs.

``start_publish`` adds the run to the job queue, which writes the requests and files into a folder of
its own and then sends them to Fusion Manage, all on its own thread; the panel polls ``list_publish_jobs``
to show the runs. ``retry_publish`` sends the folder of a failed run again: what Fusion Manage accepted is skipped.
"""

import os
import threading
from typing import Any, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.workspace_models import ITEMS_KIND
from ...core.logging_setup import get_logger, log_directory
from ...fm.client import FmApiError, FmClient
from ...fusion_mfg.graphql_client import MfgGraphQlClient
from ...publish.job_queue import JobQueue
from ...publish.panel_sections import publish_denial
from ...publish.reports import publish_report, send_report
from ...publish.runner import PublishRun
from ...publish.sender import FolderError, SendRun, load_plan
from ...publish.states import DONE, ERROR, FINISHED
from ...publish.watched import Watched
from ...publish.writer import PublishFolder
from ..file_dialogs import FileDialogs
from ..job_alerts import JobAlerts
from ..jobs_badge import JobsBadge
from ..message_bridge import MessageBridge
from .design_ref import model_ref

log = get_logger("publish_run")


def publish_root() -> str:
    """Where publish runs keep their files: ``publishes`` next to the logs in the user profile."""
    return os.path.join(os.path.dirname(log_directory()), "publishes")


def register_publish_run_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                                 dialogs: FileDialogs, badge: JobsBadge, alerts: JobAlerts) -> None:
    """Register the publish actions; the queue lives as long as the add-in."""

    watched = Watched()   # the runs the Publish panel's progress dialog is following

    def announce(run: Any) -> None:
        """A run that ends gets a message box, a warning when it failed or had failed items (the panels may be closed).
        One a progress dialog is following gets none: the dialog already shows how it ended."""
        if watched.following(run.id):
            return
        if run.kind == "send":
            failed = [row for row in run.rows if row["status"] == "error"]
            if run.phase == ERROR or failed:
                alerts.alert(send_report(run), "Send to Fusion Manage failed")
            elif run.phase == DONE:
                alerts.done(send_report(run), "Sent to Fusion Manage")
        elif run.phase == ERROR:
            alerts.alert(publish_report(run), "Publish failed")
        elif run.phase == DONE and any(row["status"] == "error" for row in run.rows):
            alerts.alert(publish_report(run), "Publish completed with errors")
        elif run.phase == DONE:
            alerts.done(publish_report(run), "Publish complete")

    # The Job Queue button on the ribbon shows whether runs are working or have failed.
    queue = JobQueue(lambda: badge.update(queue.state()), announce)

    def jobs() -> Dict[str, Any]:
        return {"jobs": queue.snapshots()}

    def start_publish(payload: Dict[str, Any]) -> Dict[str, Any]:
        cfg = config.config.workspaces.get(ITEMS_KIND)
        if not cfg or not cfg.workspace_id:
            return {"error": "Set the Items workspace ID in Settings first."}
        model_id, time = model_ref()
        if not model_id:
            return {"error": "Could not find the Data Model id of the open design."}
        # The permission check asks Fusion Manage, which can take seconds: not on Fusion's thread, or Fusion freezes. The answer is pushed.
        threading.Thread(target=lambda: begin(payload, cfg, model_id, time), daemon=True).start()
        return {"checking": True}

    def begin(payload: Dict[str, Any], cfg: Any, model_id: str, time: str) -> None:
        """Check the permissions, then queue the publish (a worker thread), and tell the panel how it went: ``error`` or ``queued``."""
        try:
            answer = check_and_queue(payload, cfg, model_id, time)
        except Exception as exc:  # noqa: BLE001 - the panel is waiting for an answer
            log.exception("Could not start the publish")
            answer = {"error": str(exc) or type(exc).__name__}
        bridge.push("start_publish_result", answer)

    def check_and_queue(payload: Dict[str, Any], cfg: Any, model_id: str, time: str) -> Dict[str, Any]:
        try:   # the panel is blocked without these permissions; this covers a page that was open when they changed
            denied = publish_denial(FmClient(config.effective_settings(), auth), cfg)
        except FmApiError as exc:
            return {"error": f"Could not check your permissions in Fusion Manage: {exc}"}
        if denied:
            return {"error": denied}
        job = {"summary": payload.get("summary") or {}, "items": list(payload.get("items") or []),
               "operations": list(payload.get("operations") or []), "root_number": str(payload.get("root_number") or "")}
        folder = PublishFolder(publish_root(), job["root_number"])   # the files stay as a record of what was sent
        settings = config.effective_settings()
        run = PublishRun(folder, job, cfg, MfgGraphQlClient(settings, auth), FmClient(settings, auth), model_id, time, send=True)
        watched.touch(run.id)   # the panel opens its progress dialog on this run
        queue.add(run)
        log.info("Publish queued into %s: %d item(s), %d BOM operation(s)", folder.path, len(job["items"]), len(job["operations"]))
        return {"queued": run.id, **jobs()}

    def retry_publish(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Queue the folder of a failed run again, in place of that run. What Fusion Manage accepted is skipped."""
        run = queue.get(str(payload.get("id") or ""))
        if run is None or run.phase not in FINISHED:
            return jobs()
        try:
            plan = load_plan(run.path)
        except FolderError as exc:
            log.warning("Retry: %s cannot be sent: %s", run.path, exc)
            dialogs.notify("Retry", str(exc))
            return jobs()
        queue.replace(run, SendRun(run.path, plan, FmClient(config.effective_settings(), auth)))
        log.info("Retry queued for %s", run.path)
        return jobs()

    def list_publish_jobs(payload: Dict[str, Any]) -> Dict[str, Any]:
        watched.touch(str((payload or {}).get("watching") or ""))   # the progress dialog names the run it follows
        return jobs()

    def cancel_publish(payload: Dict[str, Any]) -> Dict[str, Any]:
        queue.cancel(str(payload.get("id") or ""))
        return jobs()

    def clear_publish_jobs(_payload: Dict[str, Any]) -> Dict[str, Any]:
        queue.clear_finished()
        return jobs()

    def open_publish_folder(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Open the folder of a run in Explorer (only a folder a run created, never a path from the panel)."""
        run = queue.get(str(payload.get("id") or ""))
        folder = run.snapshot()["folder"] if run else ""
        if folder and os.path.isdir(folder):
            os.startfile(folder)  # noqa: S606 - Windows only, a folder we created
        return {}

    bridge.register("start_publish", start_publish)
    bridge.register("retry_publish", retry_publish)
    bridge.register("list_publish_jobs", list_publish_jobs)
    bridge.register("cancel_publish", cancel_publish)
    bridge.register("clear_publish_jobs", clear_publish_jobs)
    bridge.register("open_publish_folder", open_publish_folder)

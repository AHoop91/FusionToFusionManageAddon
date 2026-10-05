"""Palette actions for publishing: ask for a folder, queue the run, and list, cancel and open the runs.

``start_publish`` asks for the folder and adds the run to the job queue, which writes the requests
and files on its own thread; the panel polls ``list_publish_jobs`` to show the runs.
"""

import os
from typing import Any, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...core.logging_setup import get_logger
from ...fm.client import FmClient
from ...fusion_mfg.graphql_client import MfgGraphQlClient
from ...publish.job_queue import JobQueue
from ...publish.runner import ERROR, DONE, PublishRun
from ...publish.sender import FolderError, SendRun, load_plan, summarize
from ...publish.writer import PublishFolder
from ..file_dialogs import FileDialogs
from ..message_bridge import MessageBridge
from ..job_alerts import JobAlerts
from ..jobs_badge import JobsBadge
from .publish_actions import ITEMS_KIND, _model_ref

log = get_logger("publish_run")

MAX_LISTED = 5   # failed items named in the message box; the Job Queue lists them all


def _requests(run: PublishRun, method: str) -> int:
    """How many items the run wrote a request of this kind for (POST creates an item, PATCH updates one)."""
    return sum(1 for entry in list(run.folder.entries)
               if entry["artifact"] == "item request" and entry["status"] == "ok" and entry["detail"].startswith(method + " "))


def _report(run: PublishRun) -> str:
    """The text of the message box for a run that ended: how many items it processed, created and updated, and what failed."""
    failed = [row for row in run.rows if row["status"] == "error"]
    if run.phase == ERROR:
        return "\n".join([f"Publish of {run.name} could not be completed.", "", f"Reason: {run.message}"])
    lines = [f"Publish of {run.name} completed successfully." if not failed
             else f"Publish of {run.name} completed with errors: {len(failed)} of {run.total} item(s) failed.", ""]
    for row in failed[:MAX_LISTED]:
        lines.append(f"  - {row['item']}: {(row['detail'] or 'Failed.')[:160]}")
    if len(failed) > MAX_LISTED:
        lines.append(f"  - and {len(failed) - MAX_LISTED} more")
    if failed:
        lines.append("")
    lines += [f"Total Items Processed: {run.done}",
              f"Total Items Created: {_requests(run, 'POST')}",
              f"Total Items Updated: {_requests(run, 'PATCH')}", "",
              "The requests were written for review. Nothing has been sent to Fusion Manage yet."]
    if failed:
        lines.append("Open the Job Queue for the full reason of each failure.")
    return "\n".join(lines)


def _confirm_text(about: Dict[str, Any]) -> str:
    lines = [f"Send {about['root'] or 'this folder'} to Fusion Manage?", "",
             f"Tenant: {about['tenant'] or 'unknown'}   Workspace: {about['workspace_id']}", "",
             f"Items to create: {about['creates']}", f"Items to update: {about['updates']}",
             f"Bill of Materials requests: {about['bom_lines']}", ""]
    if about["sent_before"]:
        lines += [f"{about['sent_before']} request(s) were sent by an earlier try and will be skipped.", ""]
    lines.append("This changes real data in Fusion Manage.")
    return "\n".join(lines)


def _send_report(run: Any) -> str:
    """The text of the message box for a send that ended."""
    failed = [row for row in run.rows if row["status"] == "error"]
    if run.phase == ERROR:
        return f"Sending {run.name} could not be completed.\n\nReason: {run.message}"
    if not failed:
        return f"{run.name} was sent to Fusion Manage.\n\nSteps completed: {run.done} of {run.total}"
    lines = [f"Sending {run.name} finished with errors: {len(failed)} of {run.total} step(s) failed.", ""]
    lines += [f"  - {row['item']}: {(row['detail'] or 'Failed.')[:160]}" for row in failed[:MAX_LISTED]]
    if len(failed) > MAX_LISTED:
        lines.append(f"  - and {len(failed) - MAX_LISTED} more")
    lines += ["", "Send the folder again to retry: what Fusion Manage accepted is skipped."]
    return "\n".join(lines)


def register_publish_run_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                                 dialogs: FileDialogs, badge: JobsBadge, alerts: JobAlerts) -> None:
    """Register the publish actions; the queue lives as long as the add-in."""

    def announce(run: Any) -> None:
        """A run that ends gets a message box, a warning when it failed or had failed items (the panels may be closed)."""
        if run.kind == "send":
            failed = [row for row in run.rows if row["status"] == "error"]
            if run.phase == ERROR or failed:
                alerts.alert(_send_report(run), "Send to Fusion Manage failed")
            elif run.phase == DONE:
                alerts.done(_send_report(run), "Sent to Fusion Manage")
        elif run.phase == ERROR:
            alerts.alert(_report(run), "Publish failed")
        elif run.phase == DONE and any(row["status"] == "error" for row in run.rows):
            alerts.alert(_report(run), "Publish completed with errors")
        elif run.phase == DONE:
            alerts.done(_report(run), "Publish complete")

    # The Job Queue button on the ribbon shows whether runs are working or have failed.
    queue = JobQueue(lambda: badge.update(queue.state()), announce)

    def jobs() -> Dict[str, Any]:
        return {"jobs": queue.snapshots()}

    def start_publish(payload: Dict[str, Any]) -> Dict[str, Any]:
        cfg = config.config.workspaces.get(ITEMS_KIND)
        if not cfg or not cfg.workspace_id:
            return {"error": "Set the Items workspace ID in Settings first."}
        model_id, time = _model_ref()
        if not model_id:
            return {"error": "Could not find the Data Model id of the open design."}
        job = {"summary": payload.get("summary") or {}, "items": list(payload.get("items") or []),
               "operations": list(payload.get("operations") or []), "root_number": str(payload.get("root_number") or "")}
        parent = dialogs.choose_folder("Choose the folder to publish into")
        if parent is None:
            return {"cancelled": True}
        folder = PublishFolder(parent, job["root_number"])
        settings = config.effective_settings()
        run = PublishRun(folder, job, cfg, MfgGraphQlClient(settings, auth), FmClient(settings, auth), model_id, time)
        queue.add(run)
        log.info("Publish queued into %s: %d item(s), %d BOM operation(s)", folder.path, len(job["items"]), len(job["operations"]))
        return {"queued": run.id, **jobs()}

    def send_publish_folder(_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ask for a publish folder, show what sending it does, and queue the send once the user says yes."""
        path = dialogs.choose_folder("Choose the publish folder to send to Fusion Manage")
        if path is None:
            log.info("Send: no folder chosen")
            return jobs()
        try:
            plan = load_plan(path)
        except FolderError as exc:
            log.warning("Send: %s is not sendable: %s", path, exc)
            dialogs.notify("Send to Fusion Manage", str(exc))
            return jobs()
        about = summarize(path, plan)
        if not about["creates"] and not about["updates"] and not about["bom_lines"]:
            log.info("Send: %s has no requests", path)
            dialogs.notify("Send to Fusion Manage", "This folder has no requests to send.")
            return jobs()
        if not dialogs.confirm("Send to Fusion Manage", _confirm_text(about)):
            log.info("Send: not confirmed for %s", path)
            return jobs()
        queue.add(SendRun(path, plan, FmClient(config.effective_settings(), auth)))
        log.info("Send queued for %s: %s", path, about)
        return jobs()

    def list_publish_jobs(_payload: Dict[str, Any]) -> Dict[str, Any]:
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
    bridge.register("send_publish_folder", send_publish_folder)
    bridge.register("list_publish_jobs", list_publish_jobs)
    bridge.register("cancel_publish", cancel_publish)
    bridge.register("clear_publish_jobs", clear_publish_jobs)
    bridge.register("open_publish_folder", open_publish_folder)

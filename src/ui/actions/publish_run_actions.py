"""Palette actions for publishing: queue the run, retry a failed one, and list and cancel the runs.

``start_publish`` adds the run to the job queue, which writes the requests and files into a folder of
its own and then sends them to Fusion Manage, all on its own thread; the panel polls ``list_publish_jobs``
to show the runs. ``retry_publish`` sends the folder of a failed run again: what Fusion Manage accepted is skipped.
"""

from functools import partial
from typing import Any, Callable, Dict, NamedTuple, Optional, Tuple

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...core.logging_setup import get_logger
from ...core.shapes import dig
from ...fm.client import FmApiError, FmClient
from ...fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ...config.hub_context import HubContext, HubContexts
from ...publish.job_queue import JobQueue
from ...publish.job_state import JobState
from ...publish.panel_sections import publish_denial
from ...publish.reports import cut_off, publish_report, send_report
from ...publish.run_files import temp_root
from ...publish.runner import PublishRun
from ...publish.sender import FolderError, SendRun, load_plan
from ...publish.states import CANCELLED, DONE, ERROR, FINISHED
from ...publish.watched import Watched
from ...publish.writer import PublishFolder
from ..file_dialogs import FileDialogs
from ..job_alerts import JobAlerts
from ..jobs_badge import JobsBadge
from ..message_bridge import MessageBridge
from .background import Runner, in_thread, why
from .design_ref import model_ref

log = get_logger("publish_run")

RESULT_ACTION = "start_publish_result"   # pushed when the checks before queueing a publish are done


class Announcement(NamedTuple):
    """What to tell the user of a run that has ended."""

    warning: bool   # a warning (it failed, or may have left something done), else a note that it went well
    text: str
    title: str


def announcement(run: Any) -> Optional[Announcement]:
    """What to tell the user of the run that just ended, or None when there is nothing to say (the user stopped it, and no request was cut off)."""
    sending = run.kind == SendRun.kind
    report = send_report if sending else publish_report   # written only for a run there is something to say of
    if run.phase == CANCELLED:   # the user stopped it: nothing to say, unless a request was cut off and may have been done
        return Announcement(True, report(run), "Cancelled: some requests may have been done") if cut_off(run) else None
    failed_items = any(row["status"] == ERROR for row in run.rows)
    if run.phase == ERROR or (run.phase == DONE and failed_items):
        title = "Send to Fusion Manage failed" if sending else "Publish failed" if run.phase == ERROR else "Publish completed with errors"
        return Announcement(True, report(run), title)
    if run.phase == DONE:
        return Announcement(False, report(run), "Sent to Fusion Manage" if sending else "Publish complete")
    return None


def _job_of(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The publish job the panel sent, with each part in the shape the run reads."""
    return {"summary": payload.get("summary") or {}, "items": list(payload.get("items") or []),
            "operations": list(payload.get("operations") or []), "root_number": str(payload.get("root_number") or "")}


def _wrong_tenant(recorded: str, active: str) -> str:
    """Why a run cannot be retried: it was made for another Fusion Manage tenant than the one now active."""
    if not recorded:
        return "This run does not record which Fusion Manage tenant it was made for, so it cannot be retried safely. Publish again."
    return (f"This run was made for the Fusion Manage tenant '{recorded}', but the active tenant is '{active or 'none'}'. "
            f"Open the Fusion hub of '{recorded}' to retry it.")


class PublishRuns:
    """The publish runs of the add-in: the queue that works through them and what the panels may do with it. Lives as long as the add-in.

    ``open_model_ref`` gives ``(model id, timestamp)`` of the open design (Fusion's, on its thread) and ``run`` starts the permission check
    on a worker; a test gives its own. ``files_root`` is the folder the runs write into.
    """

    def __init__(self, bridge: MessageBridge, config: ConfigService, auth: AuthService, dialogs: FileDialogs, badge: JobsBadge,
                 alerts: JobAlerts, open_model_ref: Callable[[], Tuple[str, str]] = model_ref, run: Runner = in_thread,
                 files_root: Optional[str] = None) -> None:
        self._bridge, self._config, self._auth, self._dialogs, self._alerts = bridge, config, auth, dialogs, alerts
        self._contexts = HubContexts(config, auth.session)
        self._open_model_ref, self._run = open_model_ref, run
        self._files_root = files_root or temp_root()
        self._watched = Watched()   # the runs the Publish panel's progress dialog is following
        # The Job Queue button on the ribbon shows whether runs are working or have failed.
        self.queue = JobQueue(lambda: badge.update(self.queue.state()), self._announce, self._files_root)

    def jobs(self) -> Dict[str, Any]:
        return {"jobs": self.queue.snapshots()}

    def start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ask for a publish. Answers at once whether it is being checked or why it cannot start; ``start_publish_result`` follows."""
        context, reason = self._contexts.attempt()   # the hub, tenant, connection, workspace and sign-in, together, here on Fusion's thread
        if context is None:
            return {"error": reason}
        if not context.cfg or not context.cfg.workspace_id:
            return {"error": "Set the Items workspace ID in Settings first."}
        wrong = context.mismatch(payload)
        if wrong:
            log.warning("Publish refused: it was read under other settings than those now active (hub %r)", context.hub_id)
            return {"error": wrong}
        model_id, time = self._open_model_ref()
        if not model_id:
            return {"error": "Could not find the Data Model id of the open design."}
        # The permission check asks Fusion Manage, which can take seconds: not on Fusion's thread, or Fusion freezes. The answer is pushed.
        self._run(partial(self._begin, payload, context, model_id, time))
        return {"checking": True}

    def retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Queue the folder of a failed run again, in place of that run. What Fusion Manage accepted is skipped."""
        run = self.queue.get(str(payload.get("id") or ""))
        if run is None or run.phase not in FINISHED:
            return self.jobs()
        try:
            plan = load_plan(run.path)
        except FolderError as exc:
            log.warning("Retry: %s cannot be sent: %s", run.path, exc)
            self._dialogs.notify("Retry", str(exc))
            return self.jobs()
        fm = FmClient(self._config.effective_settings(), self._auth)
        recorded = str(plan["manifest"].get("tenant") or "").strip()
        if not recorded or recorded != fm.tenant:   # the active hub may have changed since: its items and workspaces are not this run's
            log.warning("Retry: %s was made for tenant %r, the active tenant is %r", run.path, recorded, fm.tenant)
            self._dialogs.notify("Retry", _wrong_tenant(recorded, fm.tenant))
            return self.jobs()
        self.queue.replace(run, SendRun(run.path, plan, fm))
        log.info("Retry queued for %s", run.path)
        return self.jobs()

    def list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._watched.touch(str(dig(payload, "watching") or ""))   # the progress dialog names the run it follows
        return self.jobs()

    def cancel(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.queue.cancel(str(payload.get("id") or ""))
        return self.jobs()

    def clear(self, _payload: Dict[str, Any]) -> Dict[str, Any]:
        self.queue.clear_finished()
        return self.jobs()

    def _begin(self, payload: Dict[str, Any], context: HubContext, model_id: str, time: str) -> None:
        """Check the permissions, then queue the publish (a worker thread), and tell the panel how it went: ``error`` or ``queued``."""
        try:
            answer = self._check_and_queue(payload, context, model_id, time)
        except Exception as exc:  # noqa: BLE001 - the panel is waiting for an answer
            log.exception("Could not start the publish")
            answer = {"error": why(exc)}
        self._bridge.push(RESULT_ACTION, answer)

    def _check_and_queue(self, payload: Dict[str, Any], context: HubContext, model_id: str, time: str) -> Dict[str, Any]:
        """Everything here reads ``context``, never the live settings: the hub may have changed since the publish was asked for."""
        try:   # the panel is blocked without these permissions; this covers a page that was open when they changed
            denied = publish_denial(FmClient(context.settings, self._auth), context.cfg)
        except FmApiError as exc:
            return {"error": f"Could not check your permissions in Fusion Manage: {exc}"}
        if denied:
            return {"error": denied}
        job = _job_of(payload)
        fm, mfg = FmClient(context.settings, self._auth), FusionGraphQlClient()
        folder = PublishFolder(self._files_root, job["root_number"])   # last of the setup: it makes the folder, and its files are kept until the run ends clean or is cleared
        run = PublishRun(folder, job, context.cfg, mfg, fm, model_id, time, send=True)
        self._watched.touch(run.id)   # the panel opens its progress dialog on this run
        self.queue.add(run)
        log.info("Publish queued into %s: %d item(s), %d BOM operation(s)", folder.path, len(job["items"]), len(job["operations"]))
        return {"queued": run.id, **self.jobs()}

    def _announce(self, run: JobState) -> None:
        """A run that ends gets a message box, a warning when it failed or had failed items (the panels may be closed).
        One a progress dialog is following gets none: the dialog already shows how it ended."""
        if self._watched.following(run.id):
            return
        told = announcement(run)
        if told is None:
            return
        (self._alerts.alert if told.warning else self._alerts.done)(told.text, told.title)


def register_publish_run_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                                 dialogs: FileDialogs, badge: JobsBadge, alerts: JobAlerts) -> None:
    """Register the publish actions; the queue lives as long as the add-in."""
    runs = PublishRuns(bridge, config, auth, dialogs, badge, alerts)
    bridge.register("start_publish", runs.start)
    bridge.register("retry_publish", runs.retry)
    bridge.register("list_publish_jobs", runs.list)
    bridge.register("cancel_publish", runs.cancel)
    bridge.register("clear_publish_jobs", runs.clear)

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
from ...publish.runner import PublishRun
from ...publish.writer import PublishFolder
from ..file_dialogs import FileDialogs
from ..message_bridge import MessageBridge
from .publish_actions import ITEMS_KIND, _model_ref

log = get_logger("publish_run")


def register_publish_run_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                                 dialogs: FileDialogs) -> None:
    """Register the publish actions; the queue lives as long as the add-in."""
    queue = JobQueue()

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
        if run and os.path.isdir(run.folder.path):
            os.startfile(run.folder.path)  # noqa: S606 - Windows only, a folder we created
        return {}

    bridge.register("start_publish", start_publish)
    bridge.register("list_publish_jobs", list_publish_jobs)
    bridge.register("cancel_publish", cancel_publish)
    bridge.register("clear_publish_jobs", clear_publish_jobs)
    bridge.register("open_publish_folder", open_publish_folder)

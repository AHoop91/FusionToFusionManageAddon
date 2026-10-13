"""Palette actions for Fusion Manage workspaces."""

import threading
from typing import Any, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import CompanyModeUnavailable, ConfigService
from ...config.workspace_models import KINDS_BY_ID
from ...fm.client import FmClient
from ...fm.workspace import WorkspaceService
from ..message_bridge import MessageBridge


def register_workspace_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register ``validate_workspace``, ``validate_workspace_status``, ``list_workspaces`` and ``list_workspaces_status``.

    Validation makes network calls, so it runs on a worker thread. Blocking
    the handler would freeze Fusion's UI thread, and with it the palette's
    animations. ``validate_workspace`` starts the work and returns at once;
    the panel then polls ``validate_workspace_status`` until it is no longer
    pending.
    """

    results: Dict[str, Dict[str, Any]] = {}   # kind id -> latest result
    lock = threading.Lock()

    def failure(kind_id: str, workspace_id: str, message: str) -> Dict[str, Any]:
        return {"kind": kind_id, "workspace_id": workspace_id, "valid": False,
                "message": message, "pending": False}

    def run(kind_id: str, workspace_id: str, client: FmClient) -> None:
        try:
            outcome = WorkspaceService(client).validate(KINDS_BY_ID[kind_id], workspace_id)
            outcome.update(workspace_id=workspace_id, pending=False)
        except Exception as exc:  # never leave the panel spinning
            outcome = failure(kind_id, workspace_id, f"Validation failed: {exc}")
        with lock:
            results[kind_id] = outcome

    def validate_workspace(payload: Dict[str, Any]) -> Dict[str, Any]:
        kind_id = str(payload.get("kind", ""))
        workspace_id = str(payload.get("workspace_id", "")).strip()
        if kind_id not in KINDS_BY_ID:
            return failure(kind_id, workspace_id, "Unknown workspace type.")
        try:
            client = FmClient(config.effective_settings(), auth)
        except CompanyModeUnavailable as exc:
            return failure(kind_id, workspace_id, str(exc))
        pending = {"kind": kind_id, "workspace_id": workspace_id, "pending": True}
        with lock:
            results[kind_id] = pending
        threading.Thread(target=run, args=(kind_id, workspace_id, client), daemon=True).start()
        return pending

    def validate_workspace_status(payload: Dict[str, Any]) -> Dict[str, Any]:
        kind_id = str(payload.get("kind", ""))
        with lock:
            return results.get(kind_id) or failure(kind_id, "", "No validation is running.")

    listing: Dict[str, Any] = {"pending": False, "ok": False, "workspaces": [], "message": ""}

    def list_run(client: FmClient) -> None:
        try:
            outcome = {"pending": False, "ok": True, "message": "",
                       "workspaces": WorkspaceService(client).revision_controlled()}
        except Exception as exc:  # never leave the panel waiting
            outcome = {"pending": False, "ok": False, "workspaces": [],
                       "message": str(exc) or type(exc).__name__}
        with lock:
            listing.update(outcome)

    def list_workspaces(_payload: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            if listing["pending"]:
                return dict(listing)
        try:
            client = FmClient(config.effective_settings(), auth)
        except CompanyModeUnavailable as exc:
            return {"pending": False, "ok": False, "workspaces": [], "message": str(exc)}
        with lock:
            listing.update(pending=True, ok=False, workspaces=[], message="")
            snapshot = dict(listing)
        threading.Thread(target=list_run, args=(client,), daemon=True).start()
        return snapshot

    def list_workspaces_status(_payload: Dict[str, Any]) -> Dict[str, Any]:
        with lock:
            return dict(listing)

    bridge.register("validate_workspace", validate_workspace)
    bridge.register("validate_workspace_status", validate_workspace_status)
    bridge.register("list_workspaces", list_workspaces)
    bridge.register("list_workspaces_status", list_workspaces_status)

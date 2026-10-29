"""Palette actions for Fusion Manage workspaces."""

import threading
from typing import Any, Callable, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import CompanyModeUnavailable, ConfigService
from ...config.workspace_models import KINDS_BY_ID
from ...fm.client import FmClient
from ...fm.workspace import WorkspaceService
from ..message_bridge import MessageBridge
from .background import BackgroundRead, Runner, in_thread, why

VALIDATE_ACTION = "validate_workspace_status"
LIST_ACTION = "list_workspaces_status"


def _failure(kind_id: str, workspace_id: str, message: str) -> Dict[str, Any]:
    return {"kind": kind_id, "workspace_id": workspace_id, "valid": False, "message": message, "pending": False}


class WorkspaceChecks:
    """Checking the workspace id typed for each kind of workspace, on a worker thread, with the outcome pushed to the panel when it is known.

    There is one outcome for each kind. A newer check of a kind replaces an older one, whose answer is dropped: a slow check of an id the
    user has since changed must not take the place of the answer for the id now typed. Any thread may use it.
    """

    def __init__(self, bridge: MessageBridge, make_client: Callable[[], FmClient], run: Runner = in_thread) -> None:
        self._bridge, self._make_client, self._run = bridge, make_client, run
        self._lock = threading.Lock()
        self._results: Dict[str, Dict[str, Any]] = {}   # kind id -> the latest outcome, pending or not
        self._requests: Dict[str, int] = {}   # kind id -> how many checks of it were asked for

    def start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start checking ``payload["workspace_id"]`` as a workspace of ``payload["kind"]``; answers at once that it is pending, or why it cannot."""
        kind_id = str(payload.get("kind", ""))
        workspace_id = str(payload.get("workspace_id", "")).strip()
        if kind_id not in KINDS_BY_ID:
            return _failure(kind_id, workspace_id, "Unknown workspace type.")
        try:
            client = self._make_client()
        except CompanyModeUnavailable as exc:
            return _failure(kind_id, workspace_id, str(exc))
        pending = {"kind": kind_id, "workspace_id": workspace_id, "pending": True}
        with self._lock:
            request = self._requests[kind_id] = self._requests.get(kind_id, 0) + 1
            self._results[kind_id] = pending
        self._run(lambda: self._finish(kind_id, workspace_id, client, request))
        return dict(pending)

    def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The latest outcome for ``payload["kind"]``, for a panel that missed the push."""
        kind_id = str(payload.get("kind", ""))
        with self._lock:
            return dict(self._results.get(kind_id) or _failure(kind_id, "", "No validation is running."))

    def _finish(self, kind_id: str, workspace_id: str, client: FmClient, request: int) -> None:
        try:
            outcome = {**WorkspaceService(client).validate(KINDS_BY_ID[kind_id], workspace_id), "workspace_id": workspace_id, "pending": False}
        except Exception as exc:  # noqa: BLE001 - never leave the panel spinning
            outcome = _failure(kind_id, workspace_id, f"Validation failed: {why(exc)}")
        with self._lock:
            if self._requests.get(kind_id) != request:   # a newer check replaced this one: its answer is not wanted
                return
            self._results[kind_id] = outcome
        self._bridge.push(VALIDATE_ACTION, outcome)   # the panel is told, not left to ask


def register_workspace_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService, run: Runner = in_thread) -> None:
    """Register ``validate_workspace``, ``validate_workspace_status``, ``list_workspaces`` and ``list_workspaces_status``.

    Both make network calls, so they run on a worker thread. Blocking the handler would freeze Fusion's UI thread, and with it the palette's
    animations. Each action starts the work and returns at once; the worker then pushes the outcome to the panel under the name of its
    ``*_status`` action when it is done.
    """

    def make_client() -> FmClient:
        return FmClient(config.effective_settings(), auth)

    checks = WorkspaceChecks(bridge, make_client, run)
    listing = BackgroundRead(bridge, LIST_ACTION, {"workspaces": []}, run)

    def prepare_list() -> Callable[[], Dict[str, Any]]:
        client = make_client()
        return lambda: {"workspaces": WorkspaceService(client).revision_controlled()}

    def list_workspaces(_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return listing.start(prepare_list)
        except CompanyModeUnavailable as exc:
            return listing.failure(str(exc))

    bridge.register("validate_workspace", checks.start)
    bridge.register(VALIDATE_ACTION, checks.status)
    bridge.register("list_workspaces", list_workspaces)
    bridge.register(LIST_ACTION, lambda _payload: listing.status())

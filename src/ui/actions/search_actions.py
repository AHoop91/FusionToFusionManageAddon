"""Palette actions for the Add Items picker of the Publish Item panel.

Each read (a page of search matches, the items the BOM holds, the filterable fields, a field's picklist options) runs on a worker thread and
the panel polls for its answer, so Fusion's palette handler never waits on the network. Only one Fusion Manage
request of the picker runs at a time. The workspace searched is always the configured Items workspace.
"""

import threading
from typing import Any, Callable, Dict

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.workspace_models import ITEMS_KIND
from ...core.logging_setup import get_logger
from ...fm.client import WORKSPACES, FmApiError, FmClient
from ...fm.item_search import ItemSearchService
from ...fm.workspace import WorkspaceService
from ..message_bridge import MessageBridge

log = get_logger("search_actions")

KEPT_ANSWERS = 30   # answers kept for the panel to poll; older tokens are dropped
NO_ITEM = "The Items workspace is not set up."
OPTIONS_PAGE = 50   # picklist options per page of a value drop-down
BAD_SEARCH = "Fusion Manage did not accept this search. Check the filter values and try again."


def register_search_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the picker's reads and their status poll."""
    lock = threading.Lock()                  # guards ``answers``
    fetching = threading.Lock()              # one Fusion Manage request at a time
    answers: Dict[str, Dict[str, Any]] = {}  # request token -> answer

    def answer(token: str, **changes: Any) -> Dict[str, Any]:
        entry = {"token": token, "pending": False, "ok": False, "result": None, "message": ""}
        entry.update(changes)
        return entry

    def store(entry: Dict[str, Any]) -> None:
        with lock:
            answers[entry["token"]] = entry
            while len(answers) > KEPT_ANSWERS:
                answers.pop(next(iter(answers)))

    def start(token: str, read: Callable[[FmClient], Any]) -> Dict[str, Any]:
        """Run ``read(client)`` on a worker thread and return the pending answer the panel polls."""
        entry = answer(token, pending=True)
        store(entry)
        client = FmClient(config.effective_settings(), auth)

        def work() -> None:
            try:
                with fetching:
                    result = read(client)
                store(answer(token, ok=True, result=result))
            except FmApiError as exc:
                log.exception("Picker read failed")
                store(answer(token, message=BAD_SEARCH if exc.status == 400 else str(exc)))
            except Exception as exc:  # never leave the panel waiting
                log.exception("Picker read failed")
                store(answer(token, message=str(exc) or type(exc).__name__))

        threading.Thread(target=work, daemon=True).start()
        return entry

    def workspace_id() -> str:
        cfg = config.config.workspaces.get(ITEMS_KIND)
        return str(cfg.workspace_id) if cfg and cfg.workspace_id else ""

    def search_items(payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(payload.get("token") or "")
        workspace, item_id = workspace_id(), str(payload.get("item_id") or "")   # no item yet while the design is not in Fusion Manage
        if not workspace:
            return answer(token, message=NO_ITEM)
        text, groups, offset = str(payload.get("text") or ""), payload.get("groups"), max(0, int(payload.get("offset") or 0))
        revision = int(payload.get("revision") or 1)
        return start(token, lambda client: ItemSearchService(client).page(workspace, item_id, text, groups, offset, revision))

    def search_members(payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(payload.get("token") or "")
        workspace, item_id = workspace_id(), str(payload.get("item_id") or "")
        if not workspace:
            return answer(token, message=NO_ITEM)
        if not item_id:   # the design is not in Fusion Manage: its Bill of Materials holds nothing yet
            return answer(token, ok=True, result={"ids": [], "numbers": []})
        return start(token, lambda client: ItemSearchService(client).members(workspace, item_id))

    def search_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(payload.get("token") or "")
        workspace = workspace_id()
        if not workspace:
            return answer(token, message=NO_ITEM)

        return start(token, lambda client: {"fields": WorkspaceService(client).filterable_fields(f"{WORKSPACES}/{workspace}")})

    def search_options(payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(payload.get("token") or "")
        lookup = str(payload.get("lookup") or "")
        if not lookup:
            return answer(token, message="No picklist was named.")
        offset, text = max(0, int(payload.get("offset") or 0)), str(payload.get("text") or "")
        return start(token, lambda client: WorkspaceService(client).options_page(lookup, offset, OPTIONS_PAGE, text))

    def search_status(payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(payload.get("token") or "")
        with lock:
            return dict(answers.get(token) or answer(token, message="Unknown request."))

    bridge.register("search_items", search_items)
    bridge.register("search_members", search_members)
    bridge.register("search_fields", search_fields)
    bridge.register("search_options", search_options)
    bridge.register("search_status", search_status)

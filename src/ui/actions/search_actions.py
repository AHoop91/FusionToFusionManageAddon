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
from ...core.shapes import whole
from ...fm.client import WORKSPACES, FmApiError, FmClient
from ...fm.item_search import ItemSearchService
from ...fm.search_query import LATEST
from ...fm.workspace import WorkspaceService
from ..message_bridge import MessageBridge
from .background import Runner, in_thread, why

log = get_logger("search_actions")

KEPT_ANSWERS = 30   # answers kept for the panel to poll; older tokens are dropped
NO_ITEM = "The Items workspace is not set up."
OPTIONS_PAGE = 50   # picklist options per page of a value drop-down
BAD_SEARCH = "Fusion Manage did not accept this search. Check the filter values and try again."
BAD_REQUEST = 400   # the status Fusion Manage answers a search it cannot read with

Read = Callable[[FmClient], Any]   # what a request does with the client, on the worker thread


def _answer(token: str, **changes: Any) -> Dict[str, Any]:
    """An answer the panel polls for by ``token``: ``pending`` while the read runs, then ``ok`` with its ``result``, or why it failed (``message``)."""
    return {"token": token, "pending": False, "ok": False, "result": None, "message": "", **changes}


def _token(payload: Dict[str, Any]) -> str:
    """The token the panel names its request by. Raises ``ValueError`` when there is none: an answer with no token cannot be asked for."""
    token = str(payload.get("token") or "")
    if not token:
        raise ValueError("The request has no token.")
    return token


class PickerReads:
    """The reads of the Add Items picker, one answer for each request token.

    ``make_client`` gives the Fusion Manage client a read uses (on the caller's thread: it reads the settings) and ``run`` starts the read on
    a worker; a test gives its own. Any thread may use it.
    """

    def __init__(self, config: ConfigService, make_client: Callable[[], FmClient], run: Runner = in_thread) -> None:
        self._config, self._make_client, self._run = config, make_client, run
        self._lock = threading.Lock()   # guards ``_answers``
        self._fetching = threading.Lock()   # one Fusion Manage request at a time
        self._answers: Dict[str, Dict[str, Any]] = {}   # request token -> answer, oldest first

    def items(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A page of the items matching the text and filters."""
        token = _token(payload)
        workspace = self._workspace()
        if not workspace:
            return _answer(token, message=NO_ITEM)
        item_id = str(payload.get("item_id") or "")   # no item yet while the design is not in Fusion Manage
        text, groups = str(payload.get("text") or ""), payload.get("groups")
        offset, revision = max(0, whole(payload.get("offset"))), whole(payload.get("revision")) or LATEST
        return self._start(token, lambda client: ItemSearchService(client).page(workspace, item_id, text, groups, offset, revision))

    def members(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The items the Bill of Materials of the design's item holds."""
        token = _token(payload)
        workspace = self._workspace()
        if not workspace:
            return _answer(token, message=NO_ITEM)
        item_id = str(payload.get("item_id") or "")
        if not item_id:   # the design is not in Fusion Manage: its Bill of Materials holds nothing yet
            return _answer(token, ok=True, result={"ids": [], "numbers": []})
        return self._start(token, lambda client: ItemSearchService(client).members(workspace, item_id))

    def fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The fields a search can filter by."""
        token = _token(payload)
        workspace = self._workspace()
        if not workspace:
            return _answer(token, message=NO_ITEM)
        return self._start(token, lambda client: {"fields": WorkspaceService(client).filterable_fields(f"{WORKSPACES}/{workspace}")})

    def options(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A page of the options of a picklist, for a value drop-down."""
        token = _token(payload)
        lookup = str(payload.get("lookup") or "")
        if not lookup:
            return _answer(token, message="No picklist was named.")
        offset, text = max(0, whole(payload.get("offset"))), str(payload.get("text") or "")
        return self._start(token, lambda client: WorkspaceService(client).options_page(lookup, offset, OPTIONS_PAGE, text))

    def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """How the request with this token stands."""
        token = _token(payload)
        with self._lock:
            return dict(self._answers.get(token) or _answer(token, message="Unknown request."))

    def _workspace(self) -> str:
        cfg = self._config.config.workspaces.get(ITEMS_KIND)
        return str(cfg.workspace_id) if cfg and cfg.workspace_id else ""

    def _keep(self, answer: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._answers[answer["token"]] = answer
            while len(self._answers) > KEPT_ANSWERS:
                self._answers.pop(next(iter(self._answers)))
        return answer

    def _start(self, token: str, read: Read) -> Dict[str, Any]:
        """Run ``read(client)`` on a worker thread and return the pending answer the panel polls."""
        client = self._make_client()   # first: when it cannot be made, no answer is left pending for ever
        pending = self._keep(_answer(token, pending=True))
        self._run(lambda: self._finish(token, client, read))
        return pending

    def _finish(self, token: str, client: FmClient, read: Read) -> None:
        try:
            with self._fetching:
                result = read(client)
            self._keep(_answer(token, ok=True, result=result))
        except FmApiError as exc:
            log.warning("Picker read failed: %s", exc)
            self._keep(_answer(token, message=BAD_SEARCH if exc.status == BAD_REQUEST else str(exc)))
        except Exception as exc:  # noqa: BLE001 - never leave the panel waiting
            log.exception("Picker read failed")
            self._keep(_answer(token, message=why(exc)))


def register_search_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the picker's reads and their status poll."""
    reads = PickerReads(config, lambda: FmClient(config.effective_settings(), auth))
    bridge.register("search_items", reads.items)
    bridge.register("search_members", reads.members)
    bridge.register("search_fields", reads.fields)
    bridge.register("search_options", reads.options)
    bridge.register("search_status", reads.status)

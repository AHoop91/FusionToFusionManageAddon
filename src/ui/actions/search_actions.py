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
from ...core.i18n import t
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
OPTIONS_PAGE = 50   # picklist options per page of a value drop-down
BAD_REQUEST = 400   # the status Fusion Manage answers a search it cannot read with


def no_item() -> str:
    return t("app.items_not_set_up")


def bad_search() -> str:
    return t("app.bad_search")

Read = Callable[[FmClient], Any]   # what a request does with the client, on the worker thread


def answer_for(token: str, **changes: Any) -> Dict[str, Any]:
    """An answer the panel polls for by ``token``: ``pending`` while the read runs, then ``ok`` with its ``result``, or why it failed (``message``)."""
    return {"token": token, "pending": False, "ok": False, "result": None, "message": "", **changes}


def token_of(payload: Dict[str, Any]) -> str:
    """The token the panel names its request by. Raises ``ValueError`` when there is none: an answer with no token cannot be asked for."""
    token = str(payload.get("token") or "")
    if not token:
        raise ValueError(t("app.request_no_token"))
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
        token = token_of(payload)
        workspace = self._workspace()
        if not workspace:
            return answer_for(token, message=no_item())
        item_id = str(payload.get("item_id") or "")   # no item yet while the design is not in Fusion Manage
        text, groups = str(payload.get("text") or ""), payload.get("groups")
        offset, revision = max(0, whole(payload.get("offset"))), whole(payload.get("revision")) or LATEST
        return self._start(token, lambda client: ItemSearchService(client).page(workspace, item_id, text, groups, offset, revision))

    def members(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The items the Bill of Materials of the design's item holds."""
        token = token_of(payload)
        workspace = self._workspace()
        if not workspace:
            return answer_for(token, message=no_item())
        item_id = str(payload.get("item_id") or "")
        if not item_id:   # the design is not in Fusion Manage: its Bill of Materials holds nothing yet
            return answer_for(token, ok=True, result={"ids": [], "numbers": []})
        return self._start(token, lambda client: ItemSearchService(client).members(workspace, item_id))

    def fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The fields a search can filter by."""
        token = token_of(payload)
        workspace = self._workspace()
        if not workspace:
            return answer_for(token, message=no_item())
        return self._start(token, lambda client: {"fields": WorkspaceService(client).filterable_fields(f"{WORKSPACES}/{workspace}")})

    def options(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """A page of the options of a picklist, for a value drop-down."""
        token = token_of(payload)
        lookup = str(payload.get("lookup") or "")
        if not lookup:
            return answer_for(token, message=t("app.no_picklist"))
        offset, text = max(0, whole(payload.get("offset"))), str(payload.get("text") or "")
        return self._start(token, lambda client: WorkspaceService(client).options_page(lookup, offset, OPTIONS_PAGE, text))

    def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """How the request with this token stands."""
        token = token_of(payload)
        with self._lock:
            return dict(self._answers.get(token) or answer_for(token, message=t("app.unknown_request")))

    def _workspace(self) -> str:
        cfg = self._config.config.workspaces.get(ITEMS_KIND)
        return str(cfg.workspace_id) if cfg and cfg.workspace_id else ""

    def _keep(self, answer: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._answers[answer["token"]] = answer
            while len(self._answers) > KEPT_ANSWERS:
                self._answers.pop(next(iter(self._answers)))
        return answer

    def _start(self, token: str, read: Read, alongside: bool = False) -> Dict[str, Any]:
        """Run ``read(client)`` on a worker thread and return the pending answer the panel polls. Reads go one at a time, unless ``alongside``
        says this one may run with the others (a picture: each is a read of its own, and a form asks for several)."""
        client = self._make_client()   # first: when it cannot be made, no answer is left pending for ever
        pending = self._keep(answer_for(token, pending=True))
        self._run(lambda: self._finish(token, client, read, alongside))
        return pending

    def _finish(self, token: str, client: FmClient, read: Read, alongside: bool = False) -> None:
        try:
            if alongside:
                result = read(client)
            else:
                with self._fetching:
                    result = read(client)
            self._keep(answer_for(token, ok=True, result=result))
        except FmApiError as exc:
            log.warning("Picker read failed: %s", exc)
            fields = getattr(exc, "fields", None)   # a write that named the fields it refused: the panel shows each beside its field
            self._keep(answer_for(token, message=bad_search() if exc.status == BAD_REQUEST and not fields else str(exc), **({"fields": fields} if fields else {})))
        except Exception as exc:  # noqa: BLE001 - never leave the panel waiting
            log.exception("Picker read failed")
            self._keep(answer_for(token, message=why(exc)))


def register_search_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the picker's reads and their status poll."""
    reads = PickerReads(config, lambda: FmClient(config.effective_settings(), auth))
    bridge.register("search_items", reads.items)
    bridge.register("search_members", reads.members)
    bridge.register("search_fields", reads.fields)
    bridge.register("search_options", reads.options)
    bridge.register("search_status", reads.status)

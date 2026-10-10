"""Palette actions for the Add Items picker of the Publish Item panel.

A page of linkable items is fetched on a worker thread and the panel polls for it, so Fusion's
palette handler never waits on the network. Later pages of an open picker are kept, but opening
the picker (the first page) always reads again, so new items show. Only one Fusion Manage request runs at a time.
"""

import threading
from typing import Any, Dict, Tuple

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.workspace_models import ITEMS_KIND
from ...core.logging_setup import get_logger
from ...fm.client import FmClient
from ...fm.linkable import LinkableService
from ..message_bridge import MessageBridge

log = get_logger("linkable_actions")

KEPT_ANSWERS = 30   # answers kept for the panel to poll; older tokens are dropped


def register_linkable_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the page load and its status poll."""
    lock = threading.Lock()                  # guards the dicts below
    fetching = threading.Lock()              # one Fusion Manage request at a time
    answers: Dict[str, Dict[str, Any]] = {}  # request token -> answer
    pages: Dict[Tuple[str, str, int, str], Dict[str, Any]] = {}   # (workspace, item, offset, sort) -> parsed page

    def answer(token: str, **changes: Any) -> Dict[str, Any]:
        entry = {"token": token, "pending": False, "ok": False, "page": None, "message": ""}
        entry.update(changes)
        return entry

    def store(entry: Dict[str, Any]) -> None:
        with lock:
            answers[entry["token"]] = entry
            while len(answers) > KEPT_ANSWERS:
                answers.pop(next(iter(answers)))

    def work(token: str, key: Tuple[str, str, int, str], service: LinkableService) -> None:
        workspace_id, item_id, offset, sort = key
        try:
            with fetching:
                page = service.page(workspace_id, item_id, offset, sort)
            with lock:
                pages[key] = page
            log.info("Linkable items %s offset %d: %d of %d", item_id, offset, page["count"], page["total"])
            store(answer(token, ok=True, page=page))
        except Exception as exc:  # never leave the panel waiting
            log.exception("Loading linkable items failed")
            store(answer(token, message=str(exc) or type(exc).__name__))

    def load_linkable_page(payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(payload.get("token") or "")
        cfg = config.config.workspaces.get(ITEMS_KIND)
        item_id = str(payload.get("item_id") or "")
        if not cfg or not cfg.workspace_id or not item_id:
            return answer(token, message="The design has no Fusion Manage item to add to.")
        key = (cfg.workspace_id, item_id, max(0, int(payload.get("offset") or 0)), "desc" if payload.get("sort") == "desc" else "asc")
        with lock:
            if key[2] == 0:   # the picker was opened (or sorted again): read the list afresh, never an old copy
                for old in [k for k in pages if k[:2] == key[:2]]:
                    del pages[old]
            cached = pages.get(key)
        if cached:
            return answer(token, ok=True, page=cached)
        entry = answer(token, pending=True)
        store(entry)
        service = LinkableService(FmClient(config.effective_settings(), auth))
        threading.Thread(target=work, args=(token, key, service), daemon=True).start()
        return entry

    def load_linkable_page_status(payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(payload.get("token") or "")
        with lock:
            return dict(answers.get(token) or answer(token, message="Unknown request."))

    bridge.register("load_linkable_page", load_linkable_page)
    bridge.register("load_linkable_page_status", load_linkable_page_status)

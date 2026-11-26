"""Find the item number of a component, then act on it on the UI thread.

``NumberFinder.find`` reads the item number of the component with a part number from the Data Model on a worker thread, then calls a
function with the ``Subject`` on the UI thread. It tells the user when the part has no item number or the read fails, and warms the layouts
of the Items workspace while the Data Model answers. The Item panel and the Export window both use it.

Layer: UI (a small collaborator of the panels). It still shows a message box, as the code did when it lived in ``ItemPanel``.
"""

import threading
from typing import Callable, NamedTuple, Optional

import adsk.core

from ..auth.auth_service import AuthService
from ..config.hub_context import HubContext, HubContexts
from ..core.cancel import Cancelled, CancelToken
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..fm.client import FmClient
from ..fm.item_view import ItemViewService
from . import fusion_selection
from .item_numbers import DesignRef, ItemNumbers, NoItemNumber, Subject
from .ui_text import item_command_name
from .ui_thread import UiThread

log = get_logger("number_finder")


class FindOptions(NamedTuple):
    """How ``NumberFinder.find`` behaves: ``quiet`` leaves a failure at the log; ``fail`` is given the reason instead of a message box showing
    it; ``cancel`` ends the find; ``ref`` is where the Data Model finds the part (else worked out); ``fresh`` reads the workspace's layout
    again instead of using what was kept (the panel is being opened, not following a selection)."""

    quiet: bool = False
    fail: Optional[Callable[[str], None]] = None
    cancel: Optional[CancelToken] = None
    ref: Optional[DesignRef] = None
    fresh: bool = False


class NumberFinder:
    """Finds the item number of a component and calls back on the UI thread."""

    # Five parameters, over the guardrail of four: each is a different collaborator the panel already holds (the message box, the UI
    # thread, the hub context, the item numbers and the sign-in), as ``ItemPanel.__init__`` has them, so a bundle object would only be a
    # second spelling of the same list.
    def __init__(self, ui: adsk.core.UserInterface, tasks: UiThread, contexts: HubContexts, numbers: ItemNumbers, auth: AuthService) -> None:
        self._ui = ui
        self._tasks = tasks
        self._contexts = contexts
        self._numbers = numbers
        self._auth = auth

    def find(self, part_number: str, then: Callable[[Subject], None], options: FindOptions = FindOptions()) -> None:
        """Read the item number of the component with ``part_number`` from the Data Model (a worker thread), then call ``then`` with it on the
        UI thread. A component with no item number is not published: the user is told (see ``FindOptions`` for how). UI thread."""
        if not self.has_number(part_number, options.quiet):
            return
        ref = options.ref or fusion_selection.part_ref(part_number)
        context, _reason = self._contexts.attempt()   # only an optimisation: what is asked for reports the settings it cannot read

        if options.fresh:
            ItemViewService.forget()

        def work() -> None:
            self.warm(context)   # the workspace's layouts are read while the Data Model answers
            try:
                subject = self._numbers.resolve(ref, part_number, options.cancel)
            except Cancelled:   # a newer selection replaced this one
                return
            except Exception as exc:  # shown to the user, never raised into a thread nobody watches
                self._report_failure(part_number, exc, options)
                return
            self._tasks.post(lambda: then(subject))

        threading.Thread(target=work, daemon=True).start()

    def _report_failure(self, part_number: str, exc: Exception, options: FindOptions) -> None:
        """Log why the item number of ``part_number`` could not be read and, unless ``options.quiet``, tell the user (``options.fail``, else a
        message box) on the UI thread. Any thread."""
        if isinstance(exc, NoItemNumber):
            log.info("No item number for %s: %s", part_number, exc)
        else:
            log.exception("Could not read the item number of %s", part_number)
        if options.quiet:
            return
        message = str(exc) or type(exc).__name__
        fail = options.fail
        self._tasks.post(lambda: fail(message) if fail else self._ui.messageBox(message, item_command_name()))

    def warm(self, context: Optional[HubContext]) -> None:
        """Read what the Items workspace of ``context`` shares between its items, ahead of the item (best effort: ``ItemPanel._read`` reports a real failure)."""
        try:
            if context is not None and context.cfg and context.cfg.workspace_id and not context.items_problem:
                threading.Thread(target=ItemViewService(FmClient(context.settings, self._auth)).prepare,
                                 args=(context.cfg.workspace_id,), daemon=True).start()   # on the add-in's token: what the next item reads too
        except Exception:  # noqa: BLE001 - only an optimisation
            log.debug("Could not prepare the Items workspace", exc_info=True)

    def has_number(self, number: str, quiet: bool = False) -> bool:
        """Whether ``number`` (a part number) names a component to look up; when not, say what to select."""
        if not number and not quiet:
            self._ui.messageBox(t("app.select_component"), item_command_name())
        return bool(number)

"""Running slow work off Fusion's thread."""

import threading
from typing import Any, Callable, Dict, Optional

from ...core.logging_setup import get_logger
from ..message_bridge import MessageBridge

log = get_logger("background")

THREAD_NAME = "MfgToFm_Background"

Runner = Callable[[Callable[[], None]], None]   # starts ``work`` somewhere that is not Fusion's thread (a test runs it when it chooses)


def in_thread(work: Callable[[], None]) -> None:
    """Run ``work`` on a thread of its own, so a network read that waits does not hold up Fusion.

    The thread is a daemon, so it never keeps Fusion from closing. What ``work`` raises is logged, not lost to a console nobody sees;
    work that has an answer to give handles its own failures, so that the panel is told.
    """
    def run() -> None:
        try:
            work()
        except Exception:  # noqa: BLE001 - the end of a thread: nothing above it can handle this
            log.exception("Background work failed")

    threading.Thread(target=run, name=THREAD_NAME, daemon=True).start()


def why(exc: Exception) -> str:
    """What to tell the user of a failure: its message, or its kind when it has none."""
    return str(exc) or type(exc).__name__


class BackgroundRead:
    """A read the panel asks for, run on a worker thread one at a time, whose outcome is pushed to the panel when it is known.

    The outcome is an object the panel reads: ``pending``, ``ok``, ``message`` and what the read gives (``blank`` says what each of those
    is while the read has not given it, e.g. ``{"properties": []}``). ``start`` answers at once that it is pending; asked again meanwhile,
    it answers how things stand and starts no second read. ``status`` gives the outcome as it stands, for a panel that missed the push.
    """

    def __init__(self, bridge: MessageBridge, action: str, blank: Optional[Dict[str, Any]] = None, run: Runner = in_thread) -> None:
        self._bridge, self._action, self._run = bridge, action, run
        self._blank: Dict[str, Any] = {"pending": False, "ok": False, "message": "", **(blank or {})}
        self._state = dict(self._blank)
        self._lock = threading.Lock()

    def start(self, prepare: Callable[[], Callable[[], Dict[str, Any]]]) -> Dict[str, Any]:
        """Begin a read, unless one is under way. ``prepare`` is called first, on the caller's thread (the one that may use Fusion's API),
        and gives the work to do on the worker thread; the work gives what the read found (it may also say ``ok`` and ``message``).
        When ``prepare`` raises nothing is started."""
        with self._lock:
            if self._state["pending"]:
                return dict(self._state)
            work = prepare()
            self._state = {**self._blank, "pending": True}
            snapshot = dict(self._state)
        self._run(lambda: self._finish(work))   # outside the lock: a runner may do the work at once, and finishing takes the lock
        return snapshot

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def failure(self, message: str) -> Dict[str, Any]:
        """The outcome of a read that could not be started, for the reply to the request. It is not kept as the outcome."""
        return {**self._blank, "message": message}

    def _finish(self, work: Callable[[], Dict[str, Any]]) -> None:
        try:
            outcome = {**self._blank, "ok": True, **work(), "pending": False}
        except Exception as exc:  # noqa: BLE001 - never leave the panel waiting
            log.exception("%s failed", self._action)
            outcome = self.failure(why(exc))
        with self._lock:
            self._state = outcome
        self._bridge.push(self._action, outcome)   # the panel is told, not left to ask

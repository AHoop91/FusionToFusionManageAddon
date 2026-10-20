"""Cancelling work that waits on the network.

``urllib`` has no cancellation of its own, so a request is cancelled the way a worker thread is told to stop elsewhere in the add-in
(``auth.callback_server``): a token that is checked before each request and each wait, and that ends the sockets of the requests
still open when it is cancelled, which ends a read that is blocked on the network (``core.http`` hands the sockets to the token as
they are made). Every client takes a ``CancelToken`` (the one for the whole add-in when none is given); work for one panel, tab or
look-up has a token of its own, a child of the add-in's, so it is cancelled when that is left or when the add-in stops. A request
cancelled raises ``Cancelled``, which is never an error to report.

Only the name lookup and the TCP connect, which have no socket to end yet, run to their own timeout.
"""

import socket
import threading
import weakref
from typing import Any, Callable, List, Optional

from .logging_setup import get_logger

log = get_logger("cancel")


class Cancelled(Exception):
    """The work was cancelled (its tab or panel was left, or the add-in stopped). Not a failure: nothing is shown for it."""


def _end(connection: Any) -> None:
    """End a socket that another thread may be blocked on. A shutdown wakes the read on Linux and macOS and a close does on Windows (where
    a shutdown does not), so it is both."""
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass   # already closed or never connected
    try:
        connection.close()
    except OSError:
        pass


class CancelToken:
    """Set once to cancel what holds it; a child is cancelled with its parent."""

    def __init__(self, parent: Optional["CancelToken"] = None, name: str = "") -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._sockets: List[Any] = []   # the connections of requests under way, to end when cancelled
        self._children: "weakref.WeakSet[CancelToken]" = weakref.WeakSet()
        self.name = name
        if parent is not None:
            with parent._lock:
                parent._children.add(self)
            if parent.cancelled:
                self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def child(self, name: str = "") -> "CancelToken":
        """A token that is cancelled when this one is, and can be cancelled alone."""
        return CancelToken(self, name)

    def cancel(self) -> None:
        """Cancel the work that holds this token (and its children's): requests open now are ended, and none starts."""
        with self._lock:
            first = not self._event.is_set()
            self._event.set()
            sockets, self._sockets = self._sockets, []
            children = list(self._children)
        if first and self.name:
            log.info("Cancelled %s", self.name)
        for connection in sockets:
            _end(connection)
        for child in children:
            child.cancel()

    def reset(self) -> None:
        """Allow work again (the add-in's own token, when it is started once more in the same process)."""
        self._event.clear()

    def check(self) -> None:
        """Raise ``Cancelled`` when cancelled."""
        if self._event.is_set():
            raise Cancelled()

    def wait(self, seconds: float) -> None:
        """Sleep ``seconds`` (a pause before another try), or raise ``Cancelled`` as soon as the token is cancelled."""
        if self._event.wait(seconds):
            raise Cancelled()

    def adopt(self, connection: Any) -> None:
        """Keep the socket of a request under way where ``cancel`` can end it. A token cancelled already ends it at once and
        raises ``Cancelled``, so a request that was cancelled while it connected goes no further."""
        with self._lock:
            if not self._event.is_set():
                self._sockets.append(connection)
                return
        _end(connection)
        raise Cancelled()

    def release(self, connections: List[Any]) -> None:
        """The request that made ``connections`` is over: they are no longer the token's to end."""
        with self._lock:
            self._sockets = [c for c in self._sockets if not any(c is done for done in connections)]


class TokenSlot:
    """The token of work that a newer start of the same work replaces (the read of the item shown, a find for the last selection): ``replace``
    cancels what the old one was still reading and gives a fresh token, a child of the token ``parent`` gives at that moment."""

    def __init__(self, parent: Callable[[], CancelToken], name: str = "") -> None:
        self._parent = parent
        self._name = name
        self.token = parent().child(name)

    def replace(self) -> CancelToken:
        self.token.cancel()
        self.token = self._parent().child(self._name)
        return self.token

    def cancel(self) -> None:
        self.token.cancel()


ADDIN = CancelToken(name="the add-in's work")   # cancelled when the add-in stops; what a client with no token of its own holds

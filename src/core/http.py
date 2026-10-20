"""The one way the add-in opens an https address.

A redirect is followed only to another https address, and the access token is sent only to the host it was meant for. A request
can be cancelled (``core.cancel``): ``open_url`` is the only place that opens one, and the connections it makes are handed to the
token as they are made, so a cancel ends a request that is connecting (once it has a socket), being answered or being read.
"""

import http.client
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional, Union

from .cancel import ADDIN, CancelToken


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect to https only, and drops the access token when it leaves the host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme.lower() != "https":
            raise urllib.error.HTTPError(req.full_url, code, f"Refused a redirect to a non-https address: {newurl}", headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and target.netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


class _Request(threading.local):
    """The request this thread is opening, for the connections made on its behalf to report to."""

    token: Optional[CancelToken] = None
    sockets: Optional[List[Any]] = None


_opening = _Request()


def _adopt(connection: Any) -> None:
    """Hand a socket just made to the token of the request being opened (nothing when none is: a connection made outside ``open_url``)."""
    if _opening.token is not None:
        _opening.token.adopt(connection)
        _opening.sockets.append(connection)


class _CancellableHTTPSConnection(http.client.HTTPSConnection):
    """Gives its sockets to the token of the request: the one made at connect (so the TLS handshake can be ended) and the one it becomes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        plain = self._create_connection

        def create(address, *rest, **more):
            connection = plain(address, *rest, **more)
            try:
                _adopt(connection)
            except BaseException:
                connection.close()   # cancelled while connecting: no request goes out on it
                raise
            return connection
        self._create_connection = create

    def connect(self) -> None:
        super().connect()
        _adopt(self.sock)   # the TLS socket that replaced the plain one


class _CancellableHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_CancellableHTTPSConnection, req, context=self._context)


OPENER = urllib.request.build_opener(_SafeRedirects, _CancellableHTTPS)


@contextmanager
def open_url(request: Union[str, urllib.request.Request], timeout: float, cancel: Optional[CancelToken] = None) -> Iterator[Any]:
    """Open ``request`` and give its response; it is closed afterwards. ``cancel`` (the add-in's own when not given) is checked first, and
    ends the connection while the request is open; a failure that follows a cancel is raised as ``Cancelled``, not as the network
    error it looks like, so no caller treats it as one worth trying again."""
    token = cancel or ADDIN
    token.check()
    sockets: List[Any] = []
    try:
        _opening.token, _opening.sockets = token, sockets
        try:
            response = OPENER.open(request, timeout=timeout)
        except Exception:
            token.check()   # cancelled while connecting
            raise
        finally:
            _opening.token = _opening.sockets = None
        try:
            with response:
                yield response
        except Exception:
            token.check()   # a read ended by the cancel, or a failure that came with it
            raise
    finally:
        token.release(sockets)

import socket
import threading
import time
import unittest
from unittest import mock

from src.core import http
from src.core.cancel import ADDIN, Cancelled, CancelToken, TokenSlot


class FakeResponse:
    """What ``OPENER.open`` gives: it can be closed, and read (``on_read`` runs first, and may make the read fail as a shut-down socket does)."""

    def __init__(self, on_read=None):
        self.closed = False
        self._on_read = on_read

    def read(self):
        if self._on_read:
            self._on_read()
        return b"{}"

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class CancelTokenTests(unittest.TestCase):
    def test_a_token_is_not_cancelled_until_it_is(self):
        token = CancelToken()
        token.check()
        token.cancel()
        self.assertTrue(token.cancelled)
        with self.assertRaises(Cancelled):
            token.check()

    def test_a_child_is_cancelled_with_its_parent_but_not_the_other_way(self):
        parent = CancelToken()
        child = parent.child()
        other = parent.child()
        child.cancel()
        self.assertTrue(child.cancelled)
        self.assertFalse(parent.cancelled)
        self.assertFalse(other.cancelled)
        parent.cancel()
        self.assertTrue(other.cancelled)

    def test_a_child_of_a_cancelled_parent_is_cancelled_at_once(self):
        parent = CancelToken()
        parent.cancel()
        self.assertTrue(parent.child().cancelled)

    def test_a_wait_ends_when_the_token_is_cancelled(self):
        token = CancelToken()
        threading.Timer(0.05, token.cancel).start()
        with self.assertRaises(Cancelled):
            token.wait(5)

    def test_a_wait_that_is_not_cancelled_just_sleeps(self):
        CancelToken().wait(0.01)

    def test_reset_allows_work_again(self):
        token = CancelToken()
        token.cancel()
        token.reset()
        token.check()


class SocketTests(unittest.TestCase):
    def test_a_cancel_ends_a_read_blocked_on_an_adopted_socket(self):
        mine, theirs = socket.socketpair()
        self.addCleanup(mine.close)
        self.addCleanup(theirs.close)
        token = CancelToken()
        token.adopt(mine)
        ended = threading.Event()

        def read():
            try:
                mine.recv(10)   # nothing is ever sent: it blocks until the socket is ended
            except OSError:
                pass
            ended.set()
        reader = threading.Thread(target=read)
        reader.start()
        time.sleep(0.05)
        token.cancel()
        self.assertTrue(ended.wait(5), "the blocked read was not ended by the cancel")
        reader.join(5)

    def test_a_socket_adopted_after_the_cancel_is_ended_and_refused(self):
        mine, theirs = socket.socketpair()
        self.addCleanup(mine.close)
        self.addCleanup(theirs.close)
        token = CancelToken()
        token.cancel()
        with self.assertRaises(Cancelled):
            token.adopt(mine)
        self.assertEqual(mine.fileno(), -1)   # closed

    def test_a_released_socket_is_left_alone_by_a_later_cancel(self):
        mine, theirs = socket.socketpair()
        self.addCleanup(mine.close)
        self.addCleanup(theirs.close)
        token = CancelToken()
        token.adopt(mine)
        token.release([mine])
        token.cancel()
        theirs.sendall(b"x")
        self.assertEqual(mine.recv(1), b"x")


class TokenSlotTests(unittest.TestCase):
    def test_replace_cancels_the_old_token_and_gives_a_live_one(self):
        slot = TokenSlot(lambda: ADDIN, "work")
        first = slot.token
        second = slot.replace()
        self.assertTrue(first.cancelled)
        self.assertFalse(second.cancelled)
        self.assertIs(slot.token, second)

    def test_the_new_token_is_a_child_of_the_parent_asked_for_at_that_moment(self):
        parents = [CancelToken(), CancelToken()]
        current = [parents[0]]
        slot = TokenSlot(lambda: current[0])
        current[0] = parents[1]
        slot.replace()
        parents[1].cancel()
        self.assertTrue(slot.token.cancelled)


class OpenUrlTests(unittest.TestCase):
    def test_a_cancelled_token_opens_nothing(self):
        token = CancelToken()
        token.cancel()
        with mock.patch.object(http.OPENER, "open") as opener:
            with self.assertRaises(Cancelled):
                with http.open_url("https://example.com", 5, token):
                    pass
        opener.assert_not_called()

    def test_the_response_is_given_and_closed(self):
        response = FakeResponse()
        with mock.patch.object(http.OPENER, "open", return_value=response):
            with http.open_url("https://example.com", 5, CancelToken()) as opened:
                self.assertIs(opened, response)
        self.assertTrue(response.closed)

    def test_a_read_that_fails_after_a_cancel_is_cancelled_not_the_network_error(self):
        token = CancelToken()

        def shut_down():   # the cancel shuts the socket down, and the read it was blocked in fails
            token.cancel()
            raise OSError("socket shut down")
        response = FakeResponse(on_read=shut_down)
        with mock.patch.object(http.OPENER, "open", return_value=response):
            with self.assertRaises(Cancelled):
                with http.open_url("https://example.com", 5, token) as opened:
                    opened.read()
        self.assertTrue(response.closed)

    def test_a_failure_with_no_cancel_is_raised_as_it_is(self):
        with mock.patch.object(http.OPENER, "open", side_effect=OSError("down")):
            with self.assertRaises(OSError):
                with http.open_url("https://example.com", 5, CancelToken()):
                    pass

    def test_a_failure_that_follows_a_cancel_while_connecting_is_cancelled(self):
        token = CancelToken()

        def connect(*_args, **_kwargs):
            token.cancel()
            raise OSError("closed")
        with mock.patch.object(http.OPENER, "open", side_effect=connect):
            with self.assertRaises(Cancelled):
                with http.open_url("https://example.com", 5, token):
                    pass

    def test_with_no_token_the_addins_is_used(self):
        response = FakeResponse()
        with mock.patch.object(http.OPENER, "open", return_value=response):
            with http.open_url("https://example.com", 5):
                ADDIN.check()


if __name__ == "__main__":
    unittest.main()

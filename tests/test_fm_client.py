"""The Fusion Manage client: what is retried, what is refused before any request, and how a refusal or an odd answer reads."""

import io
import unittest
import urllib.error
from unittest import mock

from src.config.models import ConnectionSettings
from src.core.cancel import CancelToken
from src.core import backoff
from src.fm import client as client_module
from src.fm.client import ERROR_MESSAGE_CHARS, FmApiError, FmClient


class Answer:
    """A stand-in for an HTTP response, usable as a context manager."""

    def __init__(self, body=b"{}", status=200, headers=None):
        self._body, self.status, self.headers = body, status, headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def refusal(code, body=b"", headers=None):
    return urllib.error.HTTPError("https://x", code, "no", headers or {}, io.BytesIO(body))


def make_client(tenant="acme"):
    auth = mock.Mock()
    auth.get_access_token.return_value = "token"
    return FmClient(ConnectionSettings(tenant=tenant), auth), auth


class GetJsonTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(CancelToken, "wait")   # the pause before another try
        self.waits = patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_answer_is_parsed_and_the_user_is_signed_in(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(b'{"a": 1}')) as opened:
            self.assertEqual(client.get_json("/api/v3/users/@me"), {"a": 1})
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://acme.autodeskplm360.net/api/v3/users/@me")
        self.assertEqual(request.get_header("Authorization"), "Bearer token")

    def test_no_content_is_none(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(b"", status=204)):
            self.assertIsNone(client.get_json("/api/v3/x"))

    def test_a_busy_gateway_is_tried_again(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=[refusal(503), Answer(b'{"ok": true}')]) as opened:
            self.assertEqual(client.get_json("/api/v3/x"), {"ok": True})
        self.assertEqual(opened.call_count, 2)

    def test_it_gives_up_after_the_attempts_it_is_allowed(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(503)) as opened:
            with self.assertRaises(FmApiError) as raised:
                client.get_json("/api/v3/x")
        self.assertEqual((opened.call_count, raised.exception.status), (client_module.READ_ATTEMPTS, 503))

    def test_a_refusal_that_will_not_change_is_not_tried_again(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(404)) as opened:
            with self.assertRaises(FmApiError) as raised:
                client.get_json("/api/v3/x")
        self.assertEqual((opened.call_count, raised.exception.status), (1, 404))

    def test_a_lost_connection_is_tried_again(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=[TimeoutError("slow"), Answer()]) as opened:
            client.get_json("/api/v3/x")
        self.assertEqual(opened.call_count, 2)

    def test_the_wait_the_server_asks_for_is_the_wait(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=[refusal(429, headers={"Retry-After": "7"}), Answer()]):
            client.get_json("/api/v3/x")
        waited = self.waits.call_args.args[0]
        self.assertTrue(7 <= waited <= 7 + backoff.AFTER_JITTER_SECONDS, waited)

    def test_a_server_that_asks_for_too_long_a_wait_is_not_waited_for(self):
        client, _auth = make_client()
        asked = str(int(backoff.MAX_RETRY_AFTER_SECONDS) + 1)
        with mock.patch.object(client_module, "open_url", side_effect=refusal(429, headers={"Retry-After": asked})) as opened:
            with self.assertRaises(FmApiError) as raised:
                client.get_json("/api/v3/x")
        self.assertEqual((opened.call_count, raised.exception.status), (1, 429))
        self.waits.assert_not_called()

    def test_with_no_retry_after_the_wait_grows(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(503)):
            with self.assertRaises(FmApiError):
                client.get_json("/api/v3/x")
        first, second = (call.args[0] for call in self.waits.call_args_list)
        self.assertTrue(backoff.BASE_SECONDS / 2 <= first <= backoff.BASE_SECONDS, first)
        self.assertTrue(backoff.BASE_SECONDS <= second <= backoff.BASE_SECONDS * 2, second)

    def test_an_address_that_is_refused_goes_nowhere_and_is_not_tried_again(self):
        client, auth = make_client()
        with mock.patch.object(client_module, "open_url") as opened:
            with self.assertRaises(FmApiError):
                client.get_json("/api/v3/../admin")
        opened.assert_not_called()
        auth.get_access_token.assert_not_called()

    def test_no_usable_hub_goes_nowhere_and_is_not_tried_again(self):
        client, auth = make_client(tenant="evil.example.com/")
        with mock.patch.object(client_module, "open_url") as opened:
            with self.assertRaises(FmApiError):
                client.get_json("/api/v3/x")
        opened.assert_not_called()
        auth.get_access_token.assert_not_called()


class SendJsonTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(CancelToken, "wait")   # the pause before another try
        self.waits = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_write_refused_as_too_busy_is_sent_again_after_the_wait_asked_for(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=[refusal(429, headers={"Retry-After": "3"}), Answer(status=201)]) as opened:
            self.assertEqual(client.send_json("POST", "/api/v3/x", {"a": 1}).status, 201)
        self.assertEqual(opened.call_count, 2)
        self.assertTrue(3 <= self.waits.call_args.args[0] <= 3 + backoff.AFTER_JITTER_SECONDS)

    def test_a_write_that_kept_being_refused_as_too_busy_gives_up(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(429)) as opened:
            with self.assertRaises(FmApiError):
                client.send_json("POST", "/api/v3/x", {})
        self.assertEqual(opened.call_count, client_module.WRITE_ATTEMPTS)

    def test_a_write_with_an_unknown_outcome_is_never_sent_again(self):
        client, _auth = make_client()
        for failure in (refusal(502), refusal(500), refusal(504), TimeoutError("slow")):
            with mock.patch.object(client_module, "open_url", side_effect=failure) as opened:
                with self.assertRaises(FmApiError) as raised:
                    client.send_json("POST", "/api/v3/x", {})
            self.assertEqual(opened.call_count, 1, failure)
            self.assertTrue(raised.exception.outcome_unknown)
        self.waits.assert_not_called()

    def test_the_body_goes_out_as_json(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(b'{"id": 5}', status=201, headers={"Location": "/x/5"})) as opened:
            result = client.send_json("POST", "/api/v3/x", {"a": 1})
        request = opened.call_args.args[0]
        self.assertEqual((request.get_method(), request.data, request.get_header("Content-type")), ("POST", b'{"a": 1}', "application/json"))
        self.assertEqual((result.status, result.data, result.headers["Location"]), (201, {"id": 5}, "/x/5"))

    def test_a_write_with_no_body_sends_no_content_type(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(b"", status=204)) as opened:
            result = client.send_json("DELETE", "/api/v3/x/1")
        self.assertIsNone(opened.call_args.args[0].get_header("Content-type"))
        self.assertIsNone(result.data)

    def test_an_answer_that_is_not_json_is_an_error(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(b"<html>", status=201)):
            with self.assertRaises(FmApiError):
                client.send_json("POST", "/api/v3/x", {})

    def test_a_refusal_carries_what_fusion_manage_said_but_not_all_of_it(self):
        client, _auth = make_client()
        said = b"x" * (ERROR_MESSAGE_CHARS * 2)
        with mock.patch.object(client_module, "open_url", side_effect=refusal(400, said)):
            with self.assertRaises(FmApiError) as raised:
                client.send_json("POST", "/api/v3/x", {})
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("x" * ERROR_MESSAGE_CHARS, str(raised.exception))
        self.assertNotIn("x" * (ERROR_MESSAGE_CHARS + 1), str(raised.exception))

    def test_a_write_is_not_tried_again(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(503)) as opened:
            with self.assertRaises(FmApiError):
                client.send_json("POST", "/api/v3/x", {})
        self.assertEqual(opened.call_count, 1)


class ReadableTests(unittest.TestCase):
    def test_an_embedded_file_is_cut_short_and_the_fields_around_it_are_kept(self):
        body = b'{"TITLE": "Axle", "IMAGE": "data:image/png;base64,' + b"A" * 5000 + b'", "NUMBER": "PN-1"}'
        shown = client_module._readable(body)
        self.assertIn('"TITLE": "Axle"', shown)
        self.assertIn('"NUMBER": "PN-1"', shown)
        self.assertLess(len(shown), 200)

    def test_no_body_is_empty(self):
        self.assertEqual(client_module._readable(None), "")


class PutBytesTests(unittest.TestCase):
    def test_an_address_that_is_not_https_is_refused(self):
        client, _auth = make_client()
        with mock.patch.object(client_module, "open_url") as opened:
            with self.assertRaises(FmApiError):
                client.put_bytes("http://files.example.com/x", b"data")
        opened.assert_not_called()

    def test_the_sign_in_is_not_sent_to_a_signed_address(self):
        client, auth = make_client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(status=200)) as opened:
            client.put_bytes("https://files.example.com/x?sig=1", b"data", {"x-amz-acl": "private", "Authorization": "no"})
        request = opened.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(request.get_header("X-amz-acl"), "private")
        auth.get_access_token.assert_not_called()


class WithCancelTests(unittest.TestCase):
    def test_a_client_made_with_a_token_has_it_and_the_original_keeps_its_own(self):
        from src.core.cancel import ADDIN, CancelToken
        client = FmClient(mock.Mock(tenant="acme"), mock.Mock())
        token = CancelToken()
        other = client.with_cancel(token)
        self.assertIs(other.cancel, token)
        self.assertIs(client.cancel, ADDIN)
        self.assertEqual(other.tenant, "acme")


if __name__ == "__main__":
    unittest.main()

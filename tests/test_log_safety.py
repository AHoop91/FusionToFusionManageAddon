"""What the log holds of an API call: its method, endpoint, status, duration, id, size and allowed codes, and never what the answer or the request
said, unless verbose logging is on. The answers here are made up (``example.invalid`` addresses, a name and numbers that belong to no one); the
credential names are ones the redactor does not know, so only the rule that bodies are not logged keeps them out."""

import io
import json
import logging
import unittest
import urllib.error
from unittest import mock

from src.config.models import ConnectionSettings
from src.core.constants import ADDIN_NAME
from src.auth.errors import AuthError
from src.core.logging_setup import MASK, RedactingFormatter, allowed_code, allowed_fields, describe_body, endpoint
from src.fm import client as client_module
from src.fm.client import FmApiError, FmClient
from src.fm.refusal import read_refusal
from src.fm.tableaus import TableauService
from src.fusion_mfg.fusion_graphql_client import MfgApiError, data_of

# Test data only: nothing here is real, and nothing here is a working credential.
PERSON = "Jane Q. Testperson"
EMAIL = "jane.testperson@example.invalid"
PHONE = "+00 000 000 0000"
CANARIES = (PERSON, EMAIL, PHONE, "000-00-0000", "FAKE-KEY-NOT-A-SECRET", "FAKE-SESSION-NOT-A-SECRET", "Prototype gearbox for the Unobtainium account",
            "PN-FAKE-000701")

ITEM = {
    "__self__": "/api/v3/workspaces/57/items/1",
    "title": "Prototype gearbox for the Unobtainium account",
    "number": "PN-FAKE-000701",
    "owner": {"displayName": PERSON, "email": EMAIL, "phone": PHONE, "nationalId": "000-00-0000"},
    "apiKey": "FAKE-KEY-NOT-A-SECRET",   # a credential field name the redactor has no pattern for
    "sessionSecret": "FAKE-SESSION-NOT-A-SECRET",
}
REFUSAL = {
    "statusCode": 400,
    "message": f"{PERSON} ({EMAIL}) cannot own PN-FAKE-000701",
    "errors": [{"code": "errors.required", "message": f"{PERSON} is required.", "arguments": [EMAIL], "field": {"title": PHONE}}],
    "errorCode": "GEN_INVALID_INPUT_SCHEMA",
    "errorClass": "APIError",
    "echo": ITEM,
}


class Answer:
    def __init__(self, body=b"{}", status=200, headers=None):
        self._body, self.status, self.headers = body, status, headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def refusal(code, body):
    return urllib.error.HTTPError("https://x", code, "no", {}, io.BytesIO(json.dumps(body).encode()))


class Captured(logging.Handler):
    """Collects what the log file would hold, formatted as the file's handler does."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))

    @property
    def text(self):
        return "\n".join(self.lines)


class LogTestCase(unittest.TestCase):
    level = logging.INFO   # what a log that is not verbose records

    def setUp(self):
        root = logging.getLogger(ADDIN_NAME)
        self.seen, self.before = Captured(), root.level
        root.addHandler(self.seen)
        root.setLevel(self.level)
        self.addCleanup(lambda: (root.removeHandler(self.seen), root.setLevel(self.before)))
        patcher = mock.patch.object(client_module.CancelToken, "wait")
        patcher.start()
        self.addCleanup(patcher.stop)

    def client(self):
        auth = mock.Mock()
        auth.get_access_token.return_value = "token"
        return FmClient(ConnectionSettings(tenant="acme"), auth)

    def assertNoCanary(self):
        for canary in CANARIES:
            self.assertNotIn(canary, self.seen.text)
        self.assertNotIn('"echo"', self.seen.text)


class AllowedFieldTests(unittest.TestCase):
    def test_only_codes_under_the_allowed_keys_are_kept(self):
        self.assertEqual(allowed_fields(json.dumps(REFUSAL).encode()),
                         "statusCode=400 errorCode=GEN_INVALID_INPUT_SCHEMA errorClass=APIError errors[0].code=errors.required")

    def test_free_text_under_an_allowed_key_is_not_kept(self):
        self.assertEqual(allowed_fields(json.dumps({"code": PERSON, "errorCode": EMAIL, "errorClass": "x" * 65}).encode()), "")

    def test_a_body_of_an_item_has_nothing_allowed(self):
        self.assertEqual(allowed_fields(json.dumps(ITEM).encode()), "")

    def test_what_is_not_json_or_not_an_object_has_nothing(self):
        for raw in (b"", None, b"<html>Jane Q. Testperson</html>", b"[1, 2]", b'"text"'):
            self.assertEqual(allowed_fields(raw), "")

    def test_an_answer_nested_too_deep_to_read_has_nothing_and_does_not_fail(self):
        self.assertEqual(allowed_fields(b'{"errors": ' * 100000 + b"1" + b"}" * 100000), "")

    def test_it_is_bounded(self):
        many = {"statusCode": 400, "errorCode": "A_B", "errorClass": "XError", "code": "errors.a", "errors": [{"code": f"errors.c{chr(97 + i)}"} for i in range(50)]}
        self.assertEqual(len(allowed_fields(json.dumps(many)).split()), 8)   # MAX_ALLOWED, though 9 entries of the 54 are read

    def test_a_word_that_is_not_a_code_of_that_key_is_left_out(self):
        for key, value in (("code", "PN-FAKE-000701"), ("code", "PN-700"), ("code", "AB-1234"), ("code", "jane.testperson"), ("code", "SMITH"),
                           ("errorCode", "SMITH"), ("code", "Jane.Testperson"), ("code", "jane.testperson@example.invalid"),
                           ("errorCode", "JaneTestperson"), ("errorClass", "JaneTestperson"), ("statusCode", 99999), ("statusCode", "4o4"),
                           ("errorCode", True), ("message", "ERROR_CODE")):
            self.assertFalse(allowed_code(key, value), (key, value))
        for key, value in (("code", "errors.required"), ("code", "FHQ-403"), ("code", "DATA_NOT_READY"), ("errorCode", "GEN_INVALID_INPUT_SCHEMA"),
                           ("errorClass", "APIError"),
                           ("statusCode", 400), ("statusCode", "503")):
            self.assertTrue(allowed_code(key, value), (key, value))

    def test_a_body_is_described_by_its_size_and_codes_only(self):
        described = describe_body(json.dumps(REFUSAL).encode())
        self.assertRegex(described, r"^\d+ bytes statusCode=400")
        self.assertNotIn(PERSON, described)

    def test_the_endpoint_has_no_query_or_fragment(self):
        self.assertEqual(endpoint(f"/api/v3/search?q={EMAIL}&token=abc#frag"), "/api/v3/search")


class FusionManageLogTests(LogTestCase):
    def test_a_refused_write_logs_the_call_and_codes_and_nothing_it_said_or_sent(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(400, REFUSAL)):
            with self.assertRaises(FmApiError) as raised:
                client.send_json("POST", f"/api/v3/workspaces/57/items?q={EMAIL}", {"owner": ITEM["owner"], "apiKey": ITEM["apiKey"]})
        text = self.seen.text
        self.assertIn("HTTP 400 for POST /api/v3/workspaces/57/items in ", text)
        self.assertRegex(text, r"\[[0-9a-f]{8}\]")   # the request id
        self.assertIn("errors[0].code=errors.required", text)
        self.assertIn("sent: ", text)
        self.assertNoCanary()
        self.assertNotIn(EMAIL, text)   # not even in the query string
        self.assertIn(PERSON, raised.exception.body)   # the form that shows the refusal still has all of it

    def test_an_error_wrapped_by_the_caller_has_no_server_text_in_the_traceback_either(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(400, REFUSAL)):
            with self.assertRaises(FmApiError) as raised:
                client.send_json("PATCH", "/api/v3/workspaces/57/items/1", ITEM)
        try:
            try:
                raise raised.exception
            except FmApiError as inner:
                raise ValueError(f"The item was refused: {inner}") from inner   # as the callers do, with the message in the new one
        except ValueError:
            logging.getLogger(ADDIN_NAME).getChild("caller").exception("wrapped")
        self.assertIn("Traceback", self.seen.text)
        self.assertNoCanary()

    def test_the_error_the_caller_logs_has_no_server_text_either(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(400, REFUSAL)):
            with self.assertRaises(FmApiError) as raised:
                client.send_json("PATCH", "/api/v3/workspaces/57/items/1", ITEM)
        self.assertIn(PERSON, str(raised.exception))   # the message shown to the user quotes the server
        logging.getLogger(ADDIN_NAME).getChild("caller").warning("Sending item %s failed: %s", "A", raised.exception)
        try:
            raise raised.exception
        except FmApiError:
            logging.getLogger(ADDIN_NAME).getChild("caller").exception("and with its traceback")
        self.assertIn("Sending item A failed: HTTP 400 PATCH /api/v3/workspaces/57/items/1 statusCode=400", self.seen.text)
        self.assertNoCanary()

    def test_a_refusal_read_for_a_form_logs_no_server_text(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(400, REFUSAL)):
            with self.assertRaises(FmApiError) as raised:
                client.send_json("POST", "/api/v3/workspaces/57/items", ITEM)
        refused = read_refusal(raised.exception, {"TITLE"}, "general")
        self.assertIn(PERSON, str(refused))
        logging.getLogger(ADDIN_NAME).getChild("caller").warning("refused: %s", refused)
        self.assertNoCanary()

    def test_an_accepted_write_logs_status_duration_endpoint_size_and_id(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(json.dumps(ITEM).encode(), 201)):
            client.send_json("POST", f"/api/v3/workspaces/57/items?q={EMAIL}", {"title": ITEM["title"]})
        self.assertRegex(self.seen.text, r"POST /api/v3/workspaces/57/items -> 201 in \d+\.\d\ds \[[0-9a-f]{8}\] \(\d+ bytes\)")
        self.assertNoCanary()
        self.assertNotIn(EMAIL, self.seen.text)

    def test_an_error_with_no_answer_names_the_endpoint_and_never_the_query(self):
        client = self.client()
        query = f"?search={PERSON}&mail={EMAIL}"
        for call in (lambda: client.get_json("/api/v3/items" + query), lambda: client.send_json("POST", "/api/v3/items" + query, {})):
            with mock.patch.object(client_module, "open_url", side_effect=TimeoutError("timed out")):
                with self.assertRaises(FmApiError) as raised:
                    call()
            logging.getLogger(ADDIN_NAME).getChild("caller").warning("failed: %s", raised.exception)
            self.assertIn("/api/v3/items", str(raised.exception))
        self.assertNoCanary()
        self.assertNotIn(EMAIL, self.seen.text)

    def test_a_server_error_and_a_retry_log_no_body(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=[refusal(503, REFUSAL), Answer(json.dumps(ITEM).encode())]):
            client.get_json(f"/api/v3/workspaces/57/items/1?search={PERSON}")
        self.assertIn("read of /api/v3/workspaces/57/items/1 [", self.seen.text)
        self.assertIn("again in", self.seen.text)
        self.assertNoCanary()

    def test_a_read_that_is_not_json_logs_its_size_and_not_its_content(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(f"<html>{PERSON} {EMAIL}</html>".encode(), headers={"Content-Type": "text/html"})):
            with self.assertRaises(FmApiError) as raised:
                client.get_json(f"/api/v3/x?search={PERSON}")
        logging.getLogger(ADDIN_NAME).getChild("caller").warning("failed: %s", raised.exception)
        self.assertIn("was not JSON (text/html,", self.seen.text)
        self.assertNoCanary()

    def test_a_write_answered_with_something_that_is_not_json_logs_no_content(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", return_value=Answer(f"{PERSON}".encode(), 201)):
            with self.assertRaises(FmApiError):
                client.send_json("POST", "/api/v3/x", {})
        self.assertIn("was not JSON (", self.seen.text)
        self.assertNoCanary()

    def test_a_write_refused_as_too_busy_logs_the_endpoint_and_never_the_query(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=[refusal(429, REFUSAL), Answer(status=201)]):
            client.send_json("POST", f"/api/v3/workspaces/57/items?q={EMAIL}", {})
        self.assertIn("POST /api/v3/workspaces/57/items [", self.seen.text)
        self.assertIn("refused as too busy", self.seen.text)
        self.assertNoCanary()
        self.assertNotIn(EMAIL, self.seen.text)

    def test_the_error_in_an_implicit_context_has_no_server_text_either(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(400, REFUSAL)):
            try:
                try:
                    client.send_json("PATCH", "/api/v3/workspaces/57/items/1", ITEM)
                except FmApiError as inner:
                    raise ValueError(f"The item was refused: {inner}")   # no ``from``: the error is the new one's context
            except ValueError:
                logging.getLogger(ADDIN_NAME).getChild("caller").exception("wrapped")
        self.assertIn("During handling of the above exception", self.seen.text)
        self.assertNoCanary()

    def test_a_refused_read_logs_codes_not_words(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(404, REFUSAL)):
            with self.assertRaises(FmApiError):
                client.get_json("/api/v3/workspaces/57/items/1")
        self.assertIn("HTTP 404 for GET /api/v3/workspaces/57/items/1 [", self.seen.text)
        self.assertNoCanary()

    def test_a_refused_upload_logs_neither_the_signed_address_nor_what_was_said(self):
        client = self.client()
        with mock.patch.object(client_module, "open_url", side_effect=refusal(403, REFUSAL)):
            with self.assertRaises(FmApiError):
                client.put_bytes("https://files.example.invalid/x?X-Amz-Signature=FAKE-SESSION-NOT-A-SECRET&owner=" + EMAIL, b"data")
        self.assertIn("Upload HTTP 403", self.seen.text)
        self.assertNoCanary()
        self.assertNotIn("files.example.invalid", self.seen.text)


class VerboseLogTests(LogTestCase):
    level = logging.DEBUG   # a log that is verbose, which is opt-in: ``MFGTOFM_DEBUG`` or a ``debug.flag`` file

    def test_a_verbose_log_holds_the_bodies_and_still_masks_what_it_recognises(self):
        client = self.client()
        answer = dict(ITEM, access_token="opaque-fake-token-1", title="Answer-only title FAKE")
        with mock.patch.object(client_module, "open_url", return_value=Answer(json.dumps(answer).encode(), 201)):
            client.send_json("POST", "/api/v3/workspaces/57/items", {"owner": ITEM["owner"]})
        self.assertIn(PERSON, self.seen.text)   # the body sent
        self.assertIn("answer to POST /api/v3/workspaces/57/items", self.seen.text)
        self.assertIn("Answer-only title FAKE", self.seen.text)   # the body of the answer
        self.assertNotIn("opaque-fake-token-1", self.seen.text)
        self.assertIn(MASK, self.seen.text)


class FormatterTests(unittest.TestCase):
    def format(self, message, args=None, exc_info=None):
        return RedactingFormatter("%(message)s").format(logging.LogRecord("t", logging.INFO, __file__, 1, message, args, exc_info))

    def test_a_line_break_in_quoted_text_cannot_start_a_line_of_its_own(self):
        out = self.format("Sign-in failed: %s", ("denied\r\n2026-01-01 00:00:00 INFO MfgToFm: Signed in",))
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("denied\\r\\n2026", out)

    def test_an_error_given_as_a_named_argument_is_written_as_its_log_text(self):
        error = FmApiError(f"refused: {PERSON}", 400, "{}", address="POST /a")
        self.assertEqual(self.format("%(e)s", ({"e": error},)), "HTTP 400 POST /a")

    def test_a_traceback_another_handler_formatted_first_is_not_reused(self):
        error = FmApiError(f"Fusion Manage returned 400: {PERSON}", 400, "{}", address="POST /a")
        try:
            raise error
        except FmApiError:
            import sys
            record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
        plain = logging.Formatter("%(message)s").format(record)   # a handler that does not substitute, run first, caches the traceback
        self.assertIn(PERSON, plain)
        self.assertNotIn(PERSON, RedactingFormatter("%(message)s").format(record))

    def test_an_error_whose_text_cannot_be_made_does_not_fail_the_line(self):
        class Broken(Exception):
            log_text = "broken"

            def __str__(self):
                raise RuntimeError("no text")
        try:
            raise Broken()
        except Broken:
            import sys
            out = self.format("failed", None, sys.exc_info())
        self.assertIn("failed", out)

    def test_a_short_error_message_does_not_rewrite_unrelated_text_of_the_traceback(self):
        class Short(Exception):
            log_text = "HTTP 400"
        try:
            raise Short("Error")
        except Short:
            import sys
            out = self.format("failed", None, sys.exc_info())
        self.assertIn("Traceback (most recent call last)", out)   # ``Error`` is not looked for through the traceback


class HandlerTests(unittest.TestCase):
    def test_the_file_handler_get_logger_makes_masks_and_substitutes(self):
        import tempfile
        from src.core import logging_setup
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(logging_setup, "log_directory", return_value=folder):
            logging_setup.shutdown_logging()
            try:
                logging_setup.get_logger()
                handlers = logging.getLogger(ADDIN_NAME).handlers
                self.assertTrue(handlers)
                self.assertTrue(all(isinstance(h.formatter, RedactingFormatter) for h in handlers))
            finally:
                logging_setup.shutdown_logging()


class SignInLogTests(LogTestCase):
    def test_a_refusal_the_redirect_describes_is_logged_by_its_code(self):
        error = AuthError(f"{PERSON}\n2026-01-01 INFO forged", logged="Sign-in refused (access_denied)")
        logging.getLogger(ADDIN_NAME).getChild("caller").warning("Sign-in failed: %s", error)
        self.assertIn("Sign-in failed: Sign-in refused (access_denied)", self.seen.text)
        self.assertNoCanary()

    def test_the_token_endpoint_refusal_carries_its_status(self):
        from src.auth import oauth_pkce
        with mock.patch.object(oauth_pkce, "open_url", side_effect=refusal(400, {"error": "invalid_grant", "error_description": PERSON})):
            with self.assertRaises(AuthError) as raised:
                oauth_pkce._post_token({"grant_type": "x"})
        self.assertEqual((raised.exception.status, raised.exception.log_text), (400, "Token request failed (400)"))


class OtherAnswersLogTests(LogTestCase):
    def test_a_view_read_logs_its_size_not_its_rows(self):
        service = TableauService(mock.Mock(get_json=mock.Mock(return_value={"items": [ITEM]})))
        service._read("Views", "/api/v3/workspaces/57/tableaus?size=50")
        self.assertIn("answered (", self.seen.text)
        self.assertNoCanary()

    def test_a_data_model_error_logs_its_code_and_not_its_message(self):
        payload = {"errors": [{"message": f"{PERSON} cannot read {EMAIL}", "extensions": {"code": "FHQ-403", "http": {"status": 403}}, "echo": ITEM}]}
        with self.assertRaises(MfgApiError) as raised:
            data_of(payload)
        self.assertIn(PERSON, str(raised.exception))
        logging.getLogger(ADDIN_NAME).getChild("caller").warning("query failed (%s)", raised.exception)
        self.assertIn("Data Model error HTTP 403 code=FHQ-403", self.seen.text)
        self.assertIn("1 error(s) (errors[0].extensions.code=FHQ-403)", self.seen.text)
        self.assertNoCanary()

    def test_a_code_that_is_not_code_shaped_is_left_out_of_the_error_text(self):
        error = MfgApiError(f"{PERSON} cannot read", code=PERSON, status=403, from_server=True)
        self.assertEqual(error.log_text, "Data Model error HTTP 403")

    def test_a_token_refusal_is_logged_by_its_status_not_by_what_the_endpoint_said(self):
        error = AuthError(f"Token request failed (400): {PERSON} {EMAIL}", rejected=True, status=400)
        logging.getLogger(ADDIN_NAME).getChild("caller").warning("Sign-in failed: %s", error)
        self.assertIn("Sign-in failed: Token request failed (400)", self.seen.text)
        self.assertNoCanary()

    def test_an_error_made_here_logs_its_own_words(self):
        logging.getLogger(ADDIN_NAME).getChild("caller").warning("failed: %s", MfgApiError("The Data Model did not answer in 45 seconds."))
        self.assertIn("did not answer in 45 seconds", self.seen.text)


if __name__ == "__main__":
    unittest.main()

"""The Fusion client ends a wait on a cancel or a timeout, and says what a failed answer said."""

import json
import sys
import threading
import types
import unittest
from unittest import mock

from src.core.cancel import Cancelled, CancelToken
from src.fusion_mfg import fusion_graphql_client as module
from src.fusion_mfg.fusion_graphql_client import FusionGraphQlClient, MfgApiError


class Response:
    def __init__(self, status=200, data=""):
        self.statusCode, self.data = status, data


def fusion(respond):
    """A stand-in for ``adsk.core`` whose requests are answered by ``respond()``."""
    class Request:
        data = ""

        def setHeader(self, name, value):
            pass

        def executeSync(self):
            return respond()

    core = types.SimpleNamespace(HttpRequest=types.SimpleNamespace(create=lambda url, method: Request()),
                                 HttpMethods=types.SimpleNamespace(PostMethod="POST"))
    return mock.patch.dict(sys.modules, {"adsk": types.SimpleNamespace(core=core), "adsk.core": core})


def worker(call):
    """Run ``call`` on a thread that is not the main one (the add-in's reads run on one) and give what it returned or raised."""
    outcome = {}

    def run():
        try:
            outcome["value"] = call()
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc
    thread = threading.Thread(target=run)
    thread.start()
    thread.join(10)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


class QueryTests(unittest.TestCase):
    def test_an_answer_gives_its_data(self):
        with fusion(lambda: Response(data=json.dumps({"data": {"a": 1}}))):
            self.assertEqual(worker(lambda: FusionGraphQlClient().query("query { a }")), {"a": 1})

    def test_a_failed_answer_says_why(self):
        body = json.dumps({"errors": [{"message": "Not allowed"}]})
        with fusion(lambda: Response(403, body)):
            with self.assertRaises(MfgApiError) as caught:
                worker(lambda: FusionGraphQlClient().query("query { a }"))
        self.assertIn("403: Not allowed", str(caught.exception))
        self.assertFalse(caught.exception.transient)

    def test_a_failed_answer_with_no_reason_still_gives_its_status(self):
        with fusion(lambda: Response(503, "<html>")), mock.patch.object(CancelToken, "wait"):
            with self.assertRaises(MfgApiError) as caught:
                worker(lambda: FusionGraphQlClient().query("query { a }"))
        self.assertEqual(str(caught.exception), "Manufacturing Data Model returned 503")
        self.assertTrue(caught.exception.transient)

    def test_a_cancel_ends_the_wait_for_an_answer(self):
        release = threading.Event()
        token = CancelToken()
        threading.Timer(0.3, token.cancel).start()
        with fusion(lambda: release.wait(10) and Response()), mock.patch.object(module, "POLL_SECONDS", 0.05):
            try:
                with self.assertRaises(Cancelled):
                    worker(lambda: FusionGraphQlClient(token).query("query { a }"))
            finally:
                release.set()

    def test_no_answer_in_time_is_a_busy_service(self):
        release = threading.Event()
        with fusion(lambda: release.wait(10) and Response()), mock.patch.object(module, "POLL_SECONDS", 0.05), \
                mock.patch.object(module, "REQUEST_TIMEOUT_SECONDS", 0.2), mock.patch.object(CancelToken, "wait"):
            try:
                with self.assertRaises(MfgApiError) as caught:
                    worker(lambda: FusionGraphQlClient().query("query { a }"))
            finally:
                release.set()
        self.assertTrue(caught.exception.transient)

    def test_a_cancelled_token_sends_nothing(self):
        token = CancelToken()
        token.cancel()
        sent = []
        with fusion(lambda: sent.append(1)):
            with self.assertRaises(Cancelled):
                worker(lambda: FusionGraphQlClient(token).query("query { a }"))
        self.assertEqual(sent, [])

    def test_a_call_on_the_main_thread_is_logged(self):
        with fusion(lambda: Response(data=json.dumps({"data": {}}))), mock.patch.object(module.log, "warning") as warned:
            FusionGraphQlClient().query("query { a }")
        self.assertTrue(any("own thread" in call.args[0] for call in warned.call_args_list))

    def test_a_call_on_a_worker_is_not(self):
        with fusion(lambda: Response(data=json.dumps({"data": {}}))), mock.patch.object(module.log, "warning") as warned:
            worker(lambda: FusionGraphQlClient().query("query { a }"))
        warned.assert_not_called()


if __name__ == "__main__":
    unittest.main()

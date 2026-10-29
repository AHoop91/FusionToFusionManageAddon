"""Cancelling a send ends the request under way, and sending again finds out whether the one cut off was done."""

import json
import os
import tempfile
import unittest
from unittest import mock

from src.core.cancel import Cancelled
from src.fm.client import FmApiError, SendResult
from src.publish.send_log import SEND_LOG
from src.publish.sender import Dispatcher, SendRun, load_plan
from src.publish.states import CANCELLED, DONE
from tests.test_sender import FakeFm, bom_add, create, write_folder

BOM = "/api/v3/workspaces/57/items/1/bom-items"


class Cutting(FakeFm):
    """A client whose writes are cut off by a cancel for the urls it is given (as ``open_url`` raises ``Cancelled``)."""

    def __init__(self, cut=(), answers=None):
        super().__init__()
        self.cut, self.answers = list(cut), dict(answers or {})

    def send_json(self, method, path, body=None):
        if any(part in path for part in self.cut):
            raise Cancelled()
        if (method, path) in self.answers:
            raise self.answers[(method, path)]
        return super().send_json(method, path, body)


def logged(path):
    with open(os.path.join(path, SEND_LOG), encoding="utf-8") as handle:
        return json.load(handle)


def hits(*ids):
    return mock.Mock(return_value=[{"id": i} for i in ids])


class NoAnswerTests(unittest.TestCase):
    """A write that got no answer (a timeout, a dropped connection) may have been done, like one a cancel cut off."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = self.dir.name

    def no_answer(self, *urls):
        return Cutting(answers={(method, url): FmApiError("Fusion Manage request failed: timed out") for method, url in urls})

    def test_a_create_that_got_no_answer_is_in_doubt_so_a_resend_looks_for_the_item_first(self):
        with self.assertRaises(FmApiError):
            Dispatcher(self.path, self.no_answer(("POST", "/api/v3/workspaces/57/items")), "57").send_item("A", create("A"))
        self.assertEqual(logged(self.path), {"item:A": {"in_doubt": True}})
        fm = Cutting()
        again = Dispatcher(self.path, fm, "57")
        again._search.search = hits("77")
        self.assertIn("Already created", again.send_item("A", create("A")))
        self.assertEqual(fm.sent, [])

    def test_a_create_that_was_refused_is_not_in_doubt(self):
        with self.assertRaises(FmApiError):
            Dispatcher(self.path, Cutting(answers={("POST", "/api/v3/workspaces/57/items"): FmApiError("refused", 400)}), "57").send_item("A", create("A"))
        self.assertFalse(os.path.exists(os.path.join(self.path, SEND_LOG)))

    def test_a_bom_request_that_got_no_answer_is_in_doubt_and_a_removal_that_is_gone_is_not_an_error_then(self):
        remove = {"method": "DELETE", "url": BOM + "/9", "body": None}
        with self.assertRaises(FmApiError):
            Dispatcher(self.path, self.no_answer(("DELETE", BOM + "/9")), "57").send_bom("A", [remove])
        self.assertEqual(logged(self.path), {"bom:A:0": {"in_doubt": True}})
        fm = Cutting(answers={("DELETE", BOM + "/9"): FmApiError("not found", 404)})
        Dispatcher(self.path, fm, "57").send_bom("A", [remove])
        self.assertEqual(logged(self.path), {"bom:A:0": {}})


class ItemCutOffTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = self.dir.name

    def cut_off_create(self):
        with self.assertRaises(Cancelled):
            Dispatcher(self.path, Cutting(cut=["/items"]), "57").send_item("A", create("A"))

    def test_a_create_that_was_cut_off_is_logged_as_in_doubt_not_as_done(self):
        self.cut_off_create()
        self.assertEqual(logged(self.path), {"item:A": {"in_doubt": True}})

    def test_sending_again_finds_the_item_the_cut_off_create_made_and_does_not_create_it_twice(self):
        self.cut_off_create()
        fm = Cutting()
        again = Dispatcher(self.path, fm, "57")
        again._search.search = hits("77")
        self.assertIn("Already created", again.send_item("A", create("A")))
        self.assertEqual(fm.sent, [])
        self.assertEqual(logged(self.path), {"item:A": {"id": "77"}})
        self.assertEqual(again._ids["a"], "77")

    def test_sending_again_creates_the_item_when_the_cut_off_create_made_nothing(self):
        self.cut_off_create()
        fm = Cutting()
        again = Dispatcher(self.path, fm, "57")
        again._search.search = hits()
        again.send_item("A", create("A"))
        self.assertEqual([m for m, _, _ in fm.sent], ["POST"])
        self.assertEqual(logged(self.path)["item:A"], {"id": "101"})

    def test_several_items_with_the_number_cannot_be_told_apart_so_nothing_is_sent(self):
        self.cut_off_create()
        fm = Cutting()
        again = Dispatcher(self.path, fm, "57")
        again._search.search = hits("1", "2")
        with self.assertRaises(FmApiError) as caught:
            again.send_item("A", create("A"))
        self.assertIn("matches 2 items", str(caught.exception))
        self.assertEqual(fm.sent, [])

    def test_an_update_that_was_cut_off_is_simply_sent_again(self):
        update = {"method": "PATCH", "url": "/api/v3/workspaces/57/items/7", "body": {"n": 1}}
        with self.assertRaises(Cancelled):
            Dispatcher(self.path, Cutting(cut=["/items/7"]), "57").send_item("A", update)
        fm = Cutting()
        again = Dispatcher(self.path, fm, "57")
        again._search.search = hits("7")
        again.send_item("A", update)
        self.assertEqual([m for m, _, _ in fm.sent], ["PATCH"])   # no look for it first: sending it twice does no harm
        again._search.search.assert_not_called()

    def test_an_item_that_was_accepted_is_still_skipped(self):
        first = Dispatcher(self.path, Cutting(), "57")
        first.send_item("A", create("A"))
        fm = Cutting()
        self.assertEqual(Dispatcher(self.path, fm, "57").send_item("A", create("A")), "Already sent.")
        self.assertEqual(fm.sent, [])


class BomCutOffTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = self.dir.name

    def cut_off(self, request):
        with self.assertRaises(Cancelled):
            Dispatcher(self.path, Cutting(cut=["/bom-items"]), "57").send_bom("A", [request])
        self.assertEqual(logged(self.path), {"bom:A:0": {"in_doubt": True}})

    def test_a_line_added_by_the_cut_off_request_is_not_an_error_the_second_time(self):
        add = {"method": "POST", "url": BOM, "body": {}}
        self.cut_off(add)
        fm = Cutting(answers={("POST", BOM): FmApiError("error.bom.duplicate", 400)})
        self.assertEqual(Dispatcher(self.path, fm, "57").send_bom("A", [add]), "1 request(s) sent.")
        self.assertEqual(logged(self.path), {"bom:A:0": {}})

    def test_a_line_removed_by_the_cut_off_request_is_not_an_error_the_second_time(self):
        remove = {"method": "DELETE", "url": BOM + "/9", "body": None}
        self.cut_off(remove)
        fm = Cutting(answers={("DELETE", BOM + "/9"): FmApiError("not found", 404)})
        Dispatcher(self.path, fm, "57").send_bom("A", [remove])
        self.assertEqual(logged(self.path), {"bom:A:0": {}})

    def test_a_line_that_is_missing_when_nothing_was_cut_off_is_still_an_error(self):
        remove = {"method": "DELETE", "url": BOM + "/9", "body": None}
        fm = Cutting(answers={("DELETE", BOM + "/9"): FmApiError("not found", 404)})
        with self.assertRaises(FmApiError):
            Dispatcher(self.path, fm, "57").send_bom("A", [remove])

    def test_a_request_that_was_accepted_is_still_skipped(self):
        add = {"method": "POST", "url": BOM, "body": {}}
        Dispatcher(self.path, Cutting(), "57").send_bom("A", [add])
        fm = Cutting()
        Dispatcher(self.path, fm, "57").send_bom("A", [add])
        self.assertEqual(fm.sent, [])


class SendRunCutOffTests(unittest.TestCase):
    def test_a_send_cancelled_under_way_ends_cancelled_and_names_the_item_cut_off(self):
        with tempfile.TemporaryDirectory() as root:
            write_folder(root, {"A": create("A"), "B": {"method": "POST", "url": "/api/v3/workspaces/57/items?cut", "body": {}}}, {"A": [bom_add("A", "B")]})
            run = SendRun(root, load_plan(root), Cutting(cut=["?cut"]))
            run.work()
            self.assertEqual(run.phase, CANCELLED)
            self.assertEqual([row["status"] for row in run.rows], [DONE, CANCELLED, CANCELLED])
            self.assertIn("may have done it", run.rows[1]["detail"])
            self.assertEqual(logged(root)["item:B"], {"in_doubt": True})

    def test_a_run_has_its_requests_made_under_its_token(self):
        with tempfile.TemporaryDirectory() as root:
            write_folder(root, {"A": create("A")}, {})
            fm = FakeFm()
            run = SendRun(root, load_plan(root), fm)
            self.assertIs(fm.token, run.token)


if __name__ == "__main__":
    unittest.main()

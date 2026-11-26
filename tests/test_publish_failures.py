"""Sending a publish folder to a tenant that fails, answers late or is changed by someone else.

Everything here runs the real ``SendRun``, ``Dispatcher``, ``SendLog`` and ``FmClient`` against the fake tenant (``fake_manage``), and
asserts on what the tenant holds afterwards, not on calls. The central property: *whichever single write goes wrong, and however it goes
wrong, sending the same folder again leaves the tenant exactly as a send with no fault would have, with nothing created twice.*
"""

import json
import os
import shutil
import tempfile
import unittest
import urllib.error

from src.core.i18n import t
from src.publish.send_log import SEND_LOG
from src.publish.sender import SendRun, load_plan
from src.publish.states import CANCELLED, DONE, ERROR
from tests.fake_manage import FakeManage, refusal
from tests.publish_helpers import (add, create, edges_of, end_state, remove, renumber, requantify, send, update, write_folder)


def seeded():
    """A tenant where A holds B (1), C (2) and D (3), as it was published before."""
    tenant = FakeManage()
    a = tenant.add_item("A")
    for number, sequence in (("B", 1), ("C", 2), ("D", 3)):
        tenant.add_line(a, tenant.add_item(number), sequence)
    return tenant


def republish(root, tenant):
    """The next publish of the design: E and F are new, A is updated, and A's lines change in all four ways at once. The removal frees
    position 3, which C then moves to, which frees position 2 for E: the order of the requests matters."""
    edges = edges_of(tenant, "A")
    operations = [add("A", "E", 2, "2"), renumber("A", "C", 2, 3, edges[("C", 2)]), remove("A", "D", 3, edges[("D", 3)]),
                  requantify("A", "B", 1, "5", edges[("B", 1)]), add("F", "B", 1)]
    write_folder(root, {"E": create("E"), "F": create("F"), "A": update(tenant.id_of("A"))}, operations, {"A": tenant.id_of("A")})


EXPECTED = {"numbers": {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1},
            "lines": {"A": [("B", 1, "5"), ("E", 2, "2"), ("C", 3, "1")], "B": [], "C": [], "D": [], "E": [], "F": [("B", 1, "1")]}}


class TempFolderCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def prepared(self, **faults):
        tenant = seeded()
        republish(self.root, tenant)
        return tenant


class RepublishTests(TempFolderCase):
    def test_a_republish_leaves_the_tenant_as_the_design_says(self):
        tenant = self.prepared()
        run = send(self.root, tenant)
        self.assertEqual(run.phase, DONE)
        self.assertEqual({row["status"] for row in run.rows}, {DONE})
        self.assertEqual(end_state(tenant), EXPECTED)

    def test_no_request_leaves_with_a_marker_in_it(self):
        tenant = self.prepared()
        send(self.root, tenant)
        for method, path, body in tenant.writes():
            self.assertNotIn("{{", path + json.dumps(body))

    def test_sending_the_same_folder_again_sends_nothing(self):
        tenant = self.prepared()
        send(self.root, tenant)
        before = list(tenant.log)
        run = send(self.root, tenant)
        self.assertEqual(run.phase, DONE)
        self.assertEqual(tenant.writes(), [r for r in before if r[0] != "GET"])   # not one write more
        self.assertEqual(end_state(tenant), EXPECTED)

    def test_the_log_holds_every_accepted_request_and_none_in_doubt_after_a_clean_send(self):
        tenant = self.prepared()
        send(self.root, tenant)
        with open(os.path.join(self.root, SEND_LOG), encoding="utf-8") as handle:
            logged = json.load(handle)
        self.assertEqual(len(logged), len(tenant.writes()))
        self.assertFalse([k for k, v in logged.items() if v.get("in_doubt")])


FAULTS = {
    "request lost": (lambda: OSError("connection reset"), False),
    "answer lost": (lambda: OSError("timed out"), True),
    "server error before the work": (lambda: refusal(500, "boom"), False),
    "server error after the work": (lambda: refusal(502, "bad gateway"), True),
    "gateway timeout after the work": (lambda: refusal(504, ""), True),
    "refused": (lambda: refusal(400, "error.item.invalid"), False),
    "forbidden": (lambda: refusal(403, "error.permission"), False),
    "line gone": (lambda: refusal(404, "no such line"), False),
    "stale version": (lambda: refusal(409, "error.bom.version.stale"), False),
    "too busy for good": (lambda: refusal(429, "", {"Retry-After": "1"}), False),
}


class ASingleFailureThenAResendTests(TempFolderCase):
    """Every kind of failure of every write of a publish, then a send of the same folder: the tenant ends as in a send with no fault."""

    def writes_of_a_clean_send(self):
        tenant = self.prepared()
        send(self.root, tenant)
        count = len(tenant.writes())
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        return count

    def test_whichever_write_fails_and_however_a_resend_converges(self):
        count = self.writes_of_a_clean_send()
        self.assertGreaterEqual(count, 8)   # three items and every kind of line: a smaller publish would not cover the kinds
        for name, (make, after) in FAULTS.items():
            for nth in range(1, count + 1):
                with self.subTest(fault=name, write=nth):
                    shutil.rmtree(self.root, True)
                    os.makedirs(self.root)
                    tenant = self.prepared()
                    tenant.fail("", make(), nth=nth, after=after, times=3 if "busy" in name else 1, writes_only=True)
                    first = send(self.root, tenant)
                    for number, how_many in end_state(tenant)["numbers"].items():
                        self.assertEqual(how_many, 1, f"{number} was created {how_many} times by the faulty send")
                    tenant.faults.clear()
                    again = send(self.root, tenant)
                    self.assertEqual(again.phase, DONE, [r["detail"] for r in again.rows if r["status"] != DONE])
                    self.assertEqual(end_state(tenant), EXPECTED)
                    self.assertTrue(first.phase in (DONE, ERROR))

    def test_a_failure_is_shown_on_its_row_and_never_as_done(self):
        for name in ("request lost", "answer lost", "refused", "stale version"):
            make, after = FAULTS[name]
            with self.subTest(fault=name):
                shutil.rmtree(self.root, True)
                os.makedirs(self.root)
                tenant = self.prepared()
                tenant.fail("/bom-items", make(), nth=1, after=after, writes_only=True)
                run = send(self.root, tenant)
                self.assertIn(ERROR, {row["status"] for row in run.rows})

    def test_an_unknown_outcome_says_the_write_may_have_been_done_and_a_refusal_does_not(self):
        for name, unknown in (("request lost", True), ("answer lost", True), ("server error after the work", True), ("refused", False), ("stale version", False)):
            make, after = FAULTS[name]
            with self.subTest(fault=name):
                shutil.rmtree(self.root, True)
                os.makedirs(self.root)
                tenant = self.prepared()
                tenant.fail("POST /api/v3/workspaces/57/items", make(), after=after, writes_only=True)   # the first item create
                run = send(self.root, tenant)
                failed = [row for row in run.rows if row["description"] == "Create item" and row["status"] == ERROR]
                self.assertEqual(len(failed), 1)
                self.assertEqual(t("run.send_outcome_unknown") in failed[0]["detail"], unknown)


class TheClientNeverRepeatsAWriteBlindlyTests(TempFolderCase):
    def test_a_write_that_got_a_server_error_is_sent_once_by_the_client(self):
        tenant = self.prepared()
        fault = tenant.fail("POST /api/v3/workspaces/57/items", refusal(500, "boom"), times=10, writes_only=True)
        send(self.root, tenant)
        self.assertEqual(fault.seen, 2)   # E and F, one attempt each: a repeated create could make the item twice

    def test_a_write_refused_as_too_busy_is_sent_again_and_made_once(self):
        tenant = self.prepared()
        tenant.fail("POST /api/v3/workspaces/57/items", refusal(429, "", {"Retry-After": "0"}), times=2, writes_only=True)
        run = send(self.root, tenant)
        self.assertEqual(run.phase, DONE)
        self.assertEqual(end_state(tenant), EXPECTED)

    def test_a_read_that_fails_with_a_gateway_error_is_tried_again(self):
        tenant = self.prepared()
        tenant.fail("GET /api/v3/search-results", refusal(503, ""), times=1)
        tenant.fail("POST /api/v3/workspaces/57/items", OSError("x"), after=True, writes_only=True)   # makes the resend search
        send(self.root, tenant)
        tenant.faults[1:] = []
        run = send(self.root, tenant)
        self.assertEqual(run.phase, DONE)
        self.assertEqual(end_state(tenant), EXPECTED)


class AnItemWhoseCreateMayHaveBeenDoneTests(TempFolderCase):
    """A create whose answer was lost is looked for by its number before it is sent again: found once, it is used; never found, it is made."""

    def first_create_lost(self, after):
        tenant = self.prepared()
        tenant.fail("POST /api/v3/workspaces/57/items", OSError("timed out"), after=after, writes_only=True)
        send(self.root, tenant)
        tenant.faults.clear()
        return tenant

    def creates(self, tenant):
        return [r for r in tenant.requests("POST") if r[1].endswith("/items")]

    def test_the_item_it_made_is_found_and_not_made_again(self):
        tenant = self.first_create_lost(after=True)
        before = len(self.creates(tenant))
        send(self.root, tenant)
        self.assertEqual(len(self.creates(tenant)), before)   # the resend made nothing that was there
        self.assertEqual(end_state(tenant), EXPECTED)

    def test_an_item_it_did_not_make_is_made_by_the_resend(self):
        tenant = self.first_create_lost(after=False)
        send(self.root, tenant)
        self.assertEqual(end_state(tenant), EXPECTED)

    def test_two_items_with_the_number_stop_the_resend_from_guessing(self):
        tenant = self.first_create_lost(after=True)
        made = next(n for n in "EF" if tenant.count_of(n))
        tenant.add_item(made)   # someone else made one with the same number meanwhile
        run = send(self.root, tenant)
        self.assertEqual(tenant.count_of(made), 2)   # nothing was created on top of them
        failed = [row for row in run.rows if row["item"] == made and row["status"] == ERROR]
        self.assertTrue(failed, "the create that cannot tell which item is ours must be an error")
        self.assertEqual([l for i, item in tenant.items.items() if item["number"] == made for l in tenant.bom[i]], [])   # and no line was hung on either


class AnotherUserChangesTheTenantTests(TempFolderCase):
    """Someone else edits Fusion Manage while a send is under way."""

    def test_an_item_revised_after_its_version_was_read_is_refused_and_a_resend_uses_the_new_version(self):
        tenant = FakeManage()
        tenant.add_item("B")
        write_folder(self.root, {"F": create("F")}, [add("F", "B", 1)])

        def revise(method, path, body):   # B is revised after its version was read and before the line that names it is sent
            if method == "POST" and path.endswith("/bom-items"):
                tenant.items[tenant.id_of("B")]["version"] = "[REV:x]"

        tenant.on_request = revise
        run = send(self.root, tenant)
        self.assertEqual(run.rows[-1]["status"], ERROR)
        self.assertIn("409", run.rows[-1]["detail"])
        self.assertEqual(tenant.lines_of("F"), [])   # no line of a version that is not there any more
        tenant.on_request = None
        self.assertEqual(send(self.root, tenant).phase, DONE)
        self.assertEqual(tenant.lines_of("F"), [("B", 1, "1")])
        self.assertEqual(tenant.requests("POST", "bom-items")[-1][2]["item"]["version"], "[REV:x]")   # the line names the revision B is at now

    def test_an_item_number_taken_by_someone_else_while_a_create_was_lost_is_used_not_created_again(self):
        """Characterises a limit: the item found by number is taken to be the one this send made, and the values of this send are not written to it."""
        tenant = self.prepared()
        tenant.fail("POST /api/v3/workspaces/57/items", OSError("lost"), writes_only=True)
        send(self.root, tenant)
        tenant.faults.clear()
        missing = next(n for n in "EF" if not tenant.count_of(n))
        tenant.add_item(missing)
        send(self.root, tenant)
        self.assertEqual(tenant.count_of(missing), 1)
        self.assertEqual([r for r in tenant.requests("POST") if r[1].endswith("/items") and r[2]["n"] == missing], [])

    def test_a_line_removed_by_someone_else_before_our_removal_is_an_error_and_nothing_after_it_is_sent(self):
        tenant = seeded()
        edges = edges_of(tenant, "A")
        write_folder(self.root, {"E": create("E")}, [remove("A", "D", 3, edges[("D", 3)]), add("A", "E", 3)])
        tenant.bom[tenant.id_of("A")][:] = [l for l in tenant.bom[tenant.id_of("A")] if l["item"] != tenant.id_of("D")]   # gone already
        run = send(self.root, tenant)
        self.assertEqual(run.rows[-1]["status"], ERROR)
        self.assertIn("404", run.rows[-1]["detail"])
        self.assertEqual(tenant.requests("POST", "/bom-items"), [])   # the addition after the failed removal was left unsent
        self.assertEqual(tenant.lines_of("A"), [("B", 1, "1"), ("C", 2, "1")])

    def test_a_line_that_a_cancelled_send_removed_is_not_an_error_the_second_time(self):
        tenant = seeded()
        edges = edges_of(tenant, "A")
        write_folder(self.root, {}, [remove("A", "D", 3, edges[("D", 3)])])
        tenant.fail("DELETE", OSError("cut off"), after=True, writes_only=True)
        self.assertEqual(send(self.root, tenant).rows[-1]["status"], ERROR)
        tenant.faults.clear()
        run = send(self.root, tenant)
        self.assertEqual((run.phase, run.rows[-1]["status"]), (DONE, DONE))
        self.assertEqual(tenant.lines_of("A"), [("B", 1, "1"), ("C", 2, "1")])

    def test_a_line_added_at_a_number_another_line_holds_is_added_as_fusion_manage_allows_it(self):
        tenant = seeded()
        write_folder(self.root, {"E": create("E")}, [add("A", "E", 2)])   # C holds 2 now; Fusion Manage accepts two lines at one number
        run = send(self.root, tenant)
        self.assertEqual(run.rows[-1]["status"], DONE)
        self.assertEqual(sorted(tenant.lines_of("A")), [("B", 1, "1"), ("C", 2, "1"), ("D", 3, "1"), ("E", 2, "1")])

    def test_a_line_someone_else_already_added_is_not_an_error_and_not_added_twice(self):
        tenant = seeded()
        write_folder(self.root, {"E": create("E")}, [add("A", "E", 4)])
        tenant.on_request = lambda method, path, body: (method == "POST" and path.endswith("/bom-items")
                                                        and tenant.add_line(tenant.id_of("A"), tenant.id_of("E"), 4))   # their line lands first
        run = send(self.root, tenant)
        self.assertEqual(run.rows[-1]["status"], DONE)
        self.assertEqual(tenant.lines_of("A"), [("B", 1, "1"), ("C", 2, "1"), ("D", 3, "1"), ("E", 4, "1")])

    def test_a_parent_deleted_by_someone_else_is_an_error_for_its_lines_only(self):
        tenant = seeded()
        tenant.add_item("G")
        write_folder(self.root, {"E": create("E")}, [add("A", "E", 4), add("G", "E", 1)])
        del tenant.items[tenant.id_of("A")]
        run = send(self.root, tenant)
        by_parent = {row["item"]: row["status"] for row in run.rows if row["description"].startswith("Bill of Materials")}
        self.assertEqual(by_parent.get("G"), DONE)
        self.assertEqual(by_parent.get("A"), ERROR)


class WhatWasNeverSentIsNotReportedAsInDoubtTests(TempFolderCase):
    @unittest.expectedFailure
    def test_a_bom_that_names_an_item_that_was_not_created_does_not_say_it_may_have_been_done(self):
        """KNOWN BUG, found by this test: a Bill of Materials request that is never sent because its item was not created fails with an
        ``FmApiError`` that has no status, which ``outcome_unknown`` takes for a lost answer, so the row says "Fusion Manage gave no clear
        answer, so it may have done this". Nothing was sent. A person deciding whether to check Fusion Manage by hand is told to when there is
        nothing to check."""
        tenant = self.prepared()
        tenant.fail("POST /api/v3/workspaces/57/items", refusal(400, "error.item.invalid"), writes_only=True)   # the first create is refused
        run = send(self.root, tenant)
        refused = next(r for r in run.rows if r["description"] == "Create item" and r["status"] == ERROR)
        blocked = [r for r in run.rows if r["description"].startswith("Bill of Materials") and r["status"] == ERROR and "was not created" in r["detail"]]
        self.assertTrue(blocked, [r["detail"] for r in run.rows])
        for row in blocked:
            self.assertNotIn(t("run.send_outcome_unknown"), row["detail"])
        self.assertNotIn(t("run.send_outcome_unknown"), refused["detail"])


class CancelThenResendTests(TempFolderCase):
    def test_cancelling_at_any_write_and_sending_again_gives_the_clean_result(self):
        tenant = self.prepared()
        send(self.root, tenant)
        count = len(tenant.writes())
        for nth in range(1, count + 1):
            for in_flight in ("before the work", "after the work"):
                with self.subTest(write=nth, cut=in_flight):
                    shutil.rmtree(self.root, True)
                    os.makedirs(self.root)
                    tenant = self.prepared()
                    seen = []
                    holder = {}

                    def maybe_cancel(method, path, body, seen=seen, nth=nth, holder=holder):
                        if method != "GET":
                            seen.append(1)
                            if len(seen) == nth:
                                holder["run"].cancel()

                    if in_flight == "before the work":
                        tenant.on_request = maybe_cancel
                    else:
                        tenant.on_done = maybe_cancel
                    with tenant.serving():
                        run = holder["run"] = SendRun(self.root, load_plan(self.root), tenant.client())
                        run.work()
                    self.assertEqual(run.phase, CANCELLED)
                    for number, how_many in end_state(tenant)["numbers"].items():
                        self.assertEqual(how_many, 1)
                    tenant.on_request = tenant.on_done = None
                    again = send(self.root, tenant)
                    self.assertEqual(again.phase, DONE, [r["detail"] for r in again.rows])
                    self.assertEqual(end_state(tenant), EXPECTED)


if __name__ == "__main__":
    unittest.main()

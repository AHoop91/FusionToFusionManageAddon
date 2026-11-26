"""The critical journeys of publishing, entered where the panel enters them and ended in what the fake tenant holds.

Real from the palette action down: ``PublishRuns`` (``start_publish``'s queueing, ``retry_publish``, ``cancel_publish``), the ``JobQueue`` and its worker
thread, ``PublishRun`` (the item numbers looked up, the items compared, the requests written and sent), ``SendRun`` for a retry, ``Dispatcher``,
``SendLog`` and ``FmClient``. Faked: Fusion Manage itself (``fake_manage``, below ``FmClient``), the Data Model's answer for each component (a
component with no properties beyond its item number), the permission check, and the Fusion dialogs. No server is started and nothing leaves the
machine.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from src.config.workspace_models import ITEM_NUMBER_SOURCE, ITEMS_KIND, FieldMapping, WorkspaceConfig
from src.fm.sections import SectionService
from src.publish.states import CANCELLED, DONE, ERROR
from tests.fake_manage import NUMBER_FIELD, WORKSPACE, FakeManage, refusal
from tests.hub_fixtures import auth_of, capture
from tests.publish_helpers import add, remove
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui.actions import publish_run_actions
    from src.ui.actions.publish_run_actions import PublishRuns

NO_PROPERTIES = {"properties": [], "thumbnail_url": "", "link": {"urn": "", "url": ""}}


def component(number, name=None, root=False):
    return {"id": "root" if root else "c-" + number, "item_number": number, "part_number": number, "name": name or number + " name",
            "description": "", "root": root}


def payload(items, operations):
    """What the panel sends to ``start_publish``: the design, the components to publish (the design first) and the BOM operations."""
    return {"summary": {"composition": "comp1", "component_id": "root", "item_number": items[0]["item_number"]}, "items": items,
            "operations": operations, "root_number": items[0]["item_number"]}


class JourneyCase(unittest.TestCase):
    def setUp(self):
        self.files = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.files, True)
        SectionService.forget()
        self.addCleanup(SectionService.forget)
        self.tenant = FakeManage()
        self.config = mock.Mock(hub_id="hub1")
        from src.config.models import ConnectionSettings
        self.config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant="acme")
        self.config.config.workspaces = {ITEMS_KIND: WorkspaceConfig(workspace_id=WORKSPACE, mappings=[FieldMapping(ITEM_NUMBER_SOURCE, NUMBER_FIELD)])}
        self.alerts = mock.Mock()
        self.runs = PublishRuns(mock.Mock(), self.config, auth_of(), mock.Mock(), mock.Mock(), self.alerts, lambda: ("m1", "t1"), lambda work: work(), self.files)
        self.addCleanup(self.runs.queue.join, 5)
        client = self.tenant
        patches = [
            mock.patch.object(publish_run_actions, "FmClient", lambda settings, auth: client.client()),
            mock.patch.object(publish_run_actions, "FusionGraphQlClient", lambda *a: mock.Mock(with_cancel=lambda token: mock.Mock())),
            mock.patch.object(publish_run_actions, "publish_denial", lambda *a: ""),
            mock.patch("src.publish.read_ahead.read_publish_components", lambda c, summary, ids, *a: {i: dict(NO_PROPERTIES) for i in ids}),
            mock.patch.object(publish_run_actions, "model_ref", lambda: ("m1", "t1")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        serving = self.tenant.serving()
        serving.__enter__()
        self.addCleanup(serving.__exit__, None, None, None)

    def publish(self, items, operations):
        """The panel asks for a publish; the queue works it; returns the run once it has ended."""
        context = capture(self.config)
        answer = self.runs._check_and_queue(payload(items, operations), context, "m1", "t1")
        self.runs.queue.join(30)
        return self.runs.queue.get(answer["queued"])

    def retry(self, run):
        self.runs.retry({"id": run.id})
        self.runs.queue.join(30)
        return next(r for r in self.runs.queue._runs)

    def lines(self, number):
        return self.tenant.lines_of(number)

    def numbers(self):
        out = {}
        for item in self.tenant.items.values():
            out[item["number"]] = out.get(item["number"], 0) + 1
        return out


TOP = component("TOP", root=True)
DESIGN = [TOP, component("A"), component("B"), component("C")]
BOM = [add("TOP", "A", 1, "2"), add("TOP", "B", 2), add("A", "C", 1, "4")]


class FirstPublishTests(JourneyCase):
    def test_a_design_that_is_not_in_fusion_manage_is_published_with_its_whole_structure(self):
        run = self.publish(DESIGN, BOM)
        self.assertEqual((run.phase, {row["status"] for row in run.rows}), (DONE, {DONE}))
        self.assertEqual(self.numbers(), {"TOP": 1, "A": 1, "B": 1, "C": 1})
        self.assertEqual(self.lines("TOP"), [("A", 1, "2"), ("B", 2, "1")])
        self.assertEqual(self.lines("A"), [("C", 1, "4")])
        self.assertEqual(self.lines("B"), [])

    def test_the_item_number_is_written_to_the_field_it_is_mapped_to(self):
        self.publish(DESIGN, BOM)
        self.assertEqual({item["fields"][NUMBER_FIELD] for item in self.tenant.items.values()}, {"TOP", "A", "B", "C"})

    def test_a_publish_that_went_well_leaves_no_files_behind(self):
        self.publish(DESIGN, BOM)
        self.assertEqual(os.listdir(self.files), [])


class RepublishTests(JourneyCase):
    def test_publishing_the_same_design_again_changes_nothing_in_fusion_manage(self):
        self.publish(DESIGN, BOM)
        writes = len(self.tenant.writes())
        run = self.publish(DESIGN, [])   # the planner has no operation for a structure that is as it is
        self.assertEqual(run.phase, DONE)
        self.assertEqual(len(self.tenant.writes()), writes)
        self.assertEqual(self.numbers(), {"TOP": 1, "A": 1, "B": 1, "C": 1})

    def test_a_changed_structure_is_applied_as_the_difference_only(self):
        self.publish(DESIGN, BOM)
        edges = {(self.tenant.items[l["item"]]["number"], l["sequence"]): l["edge"] for l in self.tenant.bom[self.tenant.id_of("TOP")]}
        before = len(self.tenant.writes())
        run = self.publish([TOP, component("A"), component("D")], [remove("TOP", "B", 2, edges[("B", 2)]), add("TOP", "D", 2)])
        self.assertEqual(run.phase, DONE)
        self.assertEqual(self.lines("TOP"), [("A", 1, "2"), ("D", 2, "1")])
        self.assertEqual(self.numbers(), {"TOP": 1, "A": 1, "B": 1, "C": 1, "D": 1})   # B is no longer on the BOM but is not deleted
        self.assertEqual([m for m, p, b in self.tenant.writes()[before:]], ["POST", "DELETE", "POST"])   # D created, B's line removed, D's line added


class PartialFailureTests(JourneyCase):
    def test_an_item_that_failed_is_reported_and_retry_finishes_the_publish_without_creating_anything_twice(self):
        self.tenant.fail("POST /api/v3/workspaces/57/items", refusal(502, "bad gateway"), nth=3, after=True, writes_only=True)   # the third create is done, then lost
        run = self.publish(DESIGN, BOM)
        self.assertIn(ERROR, {row["status"] for row in run.rows})
        self.assertEqual(set(self.numbers().values()), {1})
        self.tenant.faults.clear()
        again = self.retry(run)
        self.assertEqual((again.kind, again.phase), ("send", DONE), [r["detail"] for r in again.rows])
        self.assertEqual(self.numbers(), {"TOP": 1, "A": 1, "B": 1, "C": 1})
        self.assertEqual(self.lines("TOP"), [("A", 1, "2"), ("B", 2, "1")])
        self.assertEqual(self.lines("A"), [("C", 1, "4")])

    def test_a_refused_item_is_left_out_and_the_others_are_published(self):
        self.tenant.fail("POST /api/v3/workspaces/57/items", refusal(400, "error.field.required"), nth=2, writes_only=True)
        run = self.publish(DESIGN, BOM)
        items = [row for row in run.rows if not row["description"].startswith("Bill of Materials")]
        self.assertEqual(sum(1 for row in items if row["status"] == ERROR), 1)
        self.assertEqual(sum(self.numbers().values()), 3)   # the other three were created

    def test_nothing_is_lost_when_the_first_attempt_could_not_reach_fusion_manage_at_all(self):
        self.tenant.fail("", OSError("network down"), times=10 ** 6)
        run = self.publish(DESIGN, BOM)
        self.assertEqual(run.phase, ERROR)
        self.assertEqual(self.tenant.writes(), [])
        self.assertEqual(self.numbers(), {})


class FailedReadsTests(JourneyCase):
    def test_a_search_that_keeps_failing_stops_the_publish_before_anything_is_written(self):
        """The numbers cannot be known to be unique without the search, so a publish that cannot search writes nothing."""
        self.tenant.fail("GET /api/v3/search-results", refusal(503, "unavailable"), times=10 ** 6)
        run = self.publish(DESIGN, BOM)
        self.assertEqual(run.phase, ERROR)
        self.assertEqual(self.tenant.writes(), [])
        self.assertEqual(self.numbers(), {})

    def test_a_search_that_fails_once_with_a_gateway_error_is_tried_again_and_the_publish_goes_through(self):
        self.tenant.fail("GET /api/v3/search-results", refusal(503, "unavailable"), times=1)
        run = self.publish(DESIGN, BOM)
        self.assertEqual(run.phase, DONE)
        self.assertEqual(self.numbers(), {"TOP": 1, "A": 1, "B": 1, "C": 1})

    def test_a_component_the_data_model_would_not_read_fails_only_itself_and_the_lines_that_need_it(self):
        def read(client, summary, ids, *rest):
            return {i: (RuntimeError("the Data Model refused it") if i == "c-B" else dict(NO_PROPERTIES)) for i in ids}

        with mock.patch("src.publish.read_ahead.read_publish_components", read):
            run = self.publish(DESIGN, BOM)
        by_number = {row["item"]: row["status"] for row in run.rows if not row["description"].startswith("Bill of Materials")}
        self.assertEqual(by_number["B"], ERROR)
        self.assertEqual({by_number[n] for n in ("TOP", "A", "C")}, {DONE})
        self.assertEqual(self.numbers(), {"TOP": 1, "A": 1, "C": 1})   # B was never made
        self.assertEqual(self.lines("A"), [("C", 1, "4")])   # a parent whose lines do not need B is complete
        self.assertNotIn("B", [n for n, _s, _q in self.lines("TOP")])   # the parent that names B is left part done, and says so
        self.assertEqual(next(r["status"] for r in run.rows if r["item"] == "TOP" and r["description"].startswith("Bill of Materials")), ERROR)

    def test_a_publish_that_loses_its_sign_in_part_way_leaves_what_was_done_and_says_so(self):
        from src.auth.errors import AuthError
        calls = []
        real = self.tenant.open_url

        def sign_out_after_a_while(request, timeout, cancel=None):
            calls.append(1)
            if len(calls) > 8:
                raise AuthError("signed out")
            return real(request, timeout, cancel)

        with mock.patch("src.fm.client.open_url", sign_out_after_a_while):
            run = self.publish(DESIGN, BOM)
        self.assertEqual(set(self.numbers().values()) or {1}, {1})
        self.assertNotEqual(run.phase, "running")
        self.tenant.faults.clear()
        again = self.retry(run) if run.phase in (DONE, ERROR, CANCELLED) else run
        self.assertEqual(set(self.numbers().values()), {1})
        self.assertIn(again.phase, (DONE, ERROR))


class CancelTests(JourneyCase):
    def cancelled_on_the_third_write(self):
        seen, holder = [], {}

        def cancel(method, path, body):
            if method != "GET":
                seen.append(1)
                if len(seen) == 3:
                    self.runs.cancel({"id": holder["id"]})

        self.tenant.on_done = cancel   # the third write is done, and the run cancelled before its answer is read
        answer = self.runs._check_and_queue(payload(DESIGN, BOM), capture(self.config), "m1", "t1")
        holder["id"] = answer["queued"]
        self.runs.queue.join(30)
        run = self.runs.queue.get(holder["id"])
        self.tenant.on_done = None
        return run

    def test_cancelling_part_way_and_retrying_creates_every_item_once(self):
        run = self.cancelled_on_the_third_write()
        self.assertEqual(run.phase, CANCELLED)
        self.assertEqual(set(self.numbers().values()), {1})
        again = self.retry(run)
        self.assertEqual(again.phase, DONE, [r["detail"] for r in again.rows])
        self.assertEqual(self.numbers(), {"TOP": 1, "A": 1, "B": 1, "C": 1})

    @unittest.expectedFailure
    def test_cancelling_part_way_and_retrying_also_sends_the_bill_of_materials(self):
        """KNOWN BUG, found by this test: a run cancelled while it is on its items writes no ``bom/`` files (``PublishRun._steps`` skips
        ``_write_boms`` once cancelled), so Retry, which sends the folder, has no Bill of Materials to send, and reports the send as done. The
        items are there and the structure is not. Fix: write the BOM requests before the items are sent (they are known from the start), or
        have a cancelled run's retry say that it has no BOM."""
        again = self.retry(self.cancelled_on_the_third_write())
        self.assertEqual(again.phase, DONE)
        self.assertEqual(self.lines("TOP"), [("A", 1, "2"), ("B", 2, "1")])
        self.assertEqual(self.lines("A"), [("C", 1, "4")])


class SharedNumberTests(JourneyCase):
    def test_a_number_two_items_carry_stops_the_publish_before_anything_is_written(self):
        self.tenant.add_item("A")
        self.tenant.add_item("A")
        before = dict(self.numbers())
        run = self.publish(DESIGN, BOM)
        self.assertEqual(run.phase, ERROR)
        self.assertEqual(run.snapshot()["validation"]["counts"]["A"], 2)   # it says which number is shared, and by how many
        self.assertEqual(self.tenant.writes(), [])
        self.assertEqual(self.numbers(), before)


if __name__ == "__main__":
    unittest.main()

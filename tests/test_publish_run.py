"""The steps of a publish run that are its own: what it leaves out, how it names picklist options, links the component, writes the Bill of
Materials and sends it, and how it ends."""

import json
import os
import shutil
import tempfile
import threading
import types
import unittest
from unittest import mock

from src.core.cancel import Cancelled
from src.fm.client import FmApiError
from src.publish import runner
from src.publish.runner import ITEMS, VALIDATING, PublishRun, SharedItemNumbers, _needs_matching
from src.publish.sender import CUT_OFF
from src.publish.states import CANCELLED, DONE, ERROR, RUNNING
from src.publish.writer import FAILED, OK, SKIPPED, PublishFolder
from src.sync.property_compare import FOUND, MATCH, MISMATCH, NEW
from tests.test_publish_run_cancel import Client


def cfg(component_field="", workspace_id="57", mappings=()):
    return mock.Mock(workspace_id=workspace_id, static_values=[], mappings=list(mappings), maps_physical=lambda: False, component_field=component_field)


def thumbnail_to(*fields):
    """The mappings that send the thumbnail to each of these image fields."""
    return [types.SimpleNamespace(source="thumbnail", fm_field_id=field) for field in fields]


class RunTestCase(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        self.folder = PublishFolder(root, "R")

    def run_of(self, items=(), operations=(), send=False, config=None):
        job = {"summary": {}, "items": list(items), "operations": list(operations), "root_number": "R"}
        return PublishRun(self.folder, job, config or cfg(), Client("graphql"), Client("fm"), "m1", "t1", send=send)

    def recorded(self, number, artifact):
        return [e for e in self.folder.entries_of(number) if e["artifact"] == artifact]


def row(status, value, field="TITLE"):
    return {"name": field, "fm_field": field, "value": value, "status": status}


class NeedsMatchingTests(unittest.TestCase):
    def test_only_text_for_a_field_that_differs_or_is_new_needs_matching(self):
        self.assertTrue(_needs_matching(row(NEW, "Steel")))
        self.assertTrue(_needs_matching(row(MISMATCH, "Steel")))
        self.assertFalse(_needs_matching(row(MATCH, "Steel")))
        self.assertFalse(_needs_matching(row(NEW, "")))
        self.assertFalse(_needs_matching(row(NEW, 3)))   # not text
        self.assertFalse(_needs_matching(row(NEW, "/api/v3/lookups/M/options/1")))   # already an option's link
        self.assertFalse(_needs_matching({**row(NEW, "Steel"), "fm_field": ""}))   # mapped to no field
        self.assertFalse(_needs_matching({"status": NEW, "value": "Steel"}))


class OptionRowsTests(RunTestCase):
    def picklists(self, run, link, fitted=None):
        run._picklists = mock.Mock(link=mock.Mock(side_effect=lambda field, value: link(value)),
                                   fit_number=mock.Mock(side_effect=lambda field, value: value if fitted is None else fitted))

    def test_the_text_of_a_picklist_value_becomes_the_link_of_its_option(self):
        run = self.run_of()
        self.picklists(run, lambda value: "/api/v3/lookups/M/options/4")
        out = run._option_rows("PN-1", [row(NEW, "Steel")])
        self.assertEqual(out[0]["value"], "/api/v3/lookups/M/options/4")

    def test_a_value_that_matches_no_option_is_left_out_and_recorded(self):
        run = self.run_of()
        self.picklists(run, lambda value: "")
        self.assertEqual(run._option_rows("PN-1", [row(NEW, "Unobtainium")]), [])
        entry = self.recorded("PN-1", "picklist TITLE")[0]
        self.assertEqual(entry["status"], SKIPPED)
        self.assertIn("'Unobtainium' is not an option", entry["detail"])

    def test_a_value_of_a_field_that_is_not_a_picklist_is_fitted_to_its_digits(self):
        run = self.run_of()
        self.picklists(run, lambda value: None, fitted="1.50")
        self.assertEqual(run._option_rows("PN-1", [row(NEW, "1.5")])[0]["value"], "1.50")

    def test_a_row_that_needs_nothing_is_kept_as_it_is_and_the_original_is_not_changed(self):
        run = self.run_of()
        self.picklists(run, lambda value: "/api/v3/lookups/M/options/4")
        match, blank = row(MATCH, "Steel"), row(NEW, "")
        self.assertEqual(run._option_rows("PN-1", [match, blank]), [match, blank])
        changing = row(NEW, "Steel")
        run._option_rows("PN-1", [changing])
        self.assertEqual(changing["value"], "Steel")


class LeftOutTests(RunTestCase):
    def test_an_item_with_no_number_is_left_out_as_done(self):
        item = {"item_number": "", "id": "c1"}
        run = self.run_of([item])
        run._prepare(item)
        self.assertEqual((run.rows[0]["status"], run.rows[0]["detail"]), (DONE, "Skipped: no item number."))
        self.assertEqual((run.done, run.snapshot()["counts"]), (1, {"skipped": 1}))

    def test_an_item_whose_number_is_shared_is_left_out_and_says_who_shares_it(self):
        items = [{"item_number": "PN-1", "id": "c1", "name": "Axle"}, {"item_number": "pn-1", "id": "c2", "name": "Hub"}]
        run = self.run_of(items)
        run._prepare(items[0])
        self.assertEqual(run.rows[0]["status"], DONE)
        self.assertIn("shared by 2 components (Axle, Hub)", run.rows[0]["detail"])
        self.assertEqual(self.recorded("PN-1", "item")[0]["status"], SKIPPED)

    def test_nothing_is_prepared_once_the_run_is_cancelled(self):
        item = {"item_number": "PN-1", "id": "c1"}
        run = self.run_of([item])
        run.cancelled = True
        with mock.patch.object(PublishRun, "_item") as prepared:
            run._prepare(item)
        prepared.assert_not_called()

    def test_a_failure_in_one_item_is_recorded_and_the_item_is_an_error(self):
        item = {"item_number": "PN-1", "id": "c1"}
        run = self.run_of([item])
        with mock.patch.object(PublishRun, "_item", side_effect=FmApiError("down")):
            run._prepare(item)
        self.assertEqual(run.rows[0]["status"], ERROR)
        self.assertIn("down", run.rows[0]["detail"])
        self.assertEqual(run.done, 1)

    def test_an_item_that_was_prepared_is_done_and_counted_left_out_when_fusion_manage_could_not_say(self):
        item = {"item_number": "PN-1", "id": "c1"}
        for left_out, skipped in ((False, 0), (True, 1)):
            with self.subTest(left_out=left_out):
                run = self.run_of([item])
                with mock.patch.object(PublishRun, "_item", return_value=left_out):
                    run._prepare(item)
                self.assertEqual((run.rows[0]["status"], run.snapshot()["counts"]["skipped"]), (DONE, skipped))


class ThumbnailRequestTests(RunTestCase):
    """The thumbnail cannot be compared with Fusion Manage's, so every item that is created or updated gets it."""

    SECTIONS = {"IMAGE": "/api/v3/workspaces/57/sections/1", "ICON": "/api/v3/workspaces/57/sections/1", "TITLE": "/api/v3/workspaces/57/sections/1"}
    IMAGE = "data:image/png;base64,AA"

    def request(self, state, mapped=("IMAGE",), image=IMAGE, rows=()):
        run = self.run_of(config=cfg(mappings=thumbnail_to(*mapped)))
        run._field_sections = dict(self.SECTIONS)
        result = {"fm": {"state": state, "item_id": "7"}, "values": {}}
        with mock.patch.object(PublishRun, "_thumbnail", return_value=image) as thumbnail:
            request, reason = run._request("PN-1", self.folder.path, "c1", "https://x.example/t.png", result, list(rows), None)
        return run, request, reason, thumbnail

    def test_an_item_whose_other_values_match_still_gets_its_thumbnail(self):
        _, request, _, thumbnail = self.request(FOUND, rows=[row(MATCH, "A")])
        thumbnail.assert_called_once()
        self.assertEqual((request["method"], request["url"]), ("PATCH", "/api/v3/workspaces/57/items/7"))
        field = request["body"]["sections"][0]["fields"][0]
        self.assertEqual((field["__self__"].rsplit("/", 1)[-1], field["value"]), ("IMAGE", self.IMAGE))
        self.assertEqual(len(request["body"]["sections"][0]["fields"]), 1)   # nothing else is sent

    def test_a_new_item_gets_its_thumbnail(self):
        _, request, _, _ = self.request(NEW, rows=[row(NEW, "Axle")])
        self.assertEqual(request["method"], "POST")
        self.assertEqual(sorted(f["__self__"].rsplit("/", 1)[-1] for f in request["body"]["sections"][0]["fields"]), ["IMAGE", "TITLE"])

    def test_every_field_the_thumbnail_is_mapped_to_gets_it(self):
        _, request, _, thumbnail = self.request(FOUND, mapped=("IMAGE", "ICON"))
        thumbnail.assert_called_once()   # fetched once
        self.assertEqual(sorted(f["__self__"].rsplit("/", 1)[-1] for f in request["body"]["sections"][0]["fields"]), ["ICON", "IMAGE"])

    def test_an_item_that_is_neither_new_nor_found_is_not_given_a_thumbnail_to_fetch(self):
        run, request, _, thumbnail = self.request("error")
        thumbnail.assert_not_called()
        self.assertIsNone(request)
        self.assertEqual(self.recorded("PN-1", "thumbnail")[0]["status"], SKIPPED)

    def test_with_no_field_mapped_to_the_thumbnail_none_is_fetched_and_nothing_is_sent_for_matching_values(self):
        run, request, reason, thumbnail = self.request(FOUND, mapped=(), rows=[row(MATCH, "A")])
        thumbnail.assert_not_called()
        self.assertIsNone(request)
        self.assertEqual(reason, "Fusion Manage already has the same values.")
        self.assertEqual(self.recorded("PN-1", "thumbnail")[0]["detail"], "No field is mapped to the thumbnail.")

    def test_a_thumbnail_that_could_not_be_had_leaves_matching_values_with_nothing_to_send(self):
        _, request, reason, thumbnail = self.request(FOUND, image="", rows=[row(MATCH, "A")])
        thumbnail.assert_called_once()
        self.assertIsNone(request)
        self.assertEqual(reason, "Fusion Manage already has the same values.")

    def test_a_thumbnail_that_could_not_be_had_does_not_stop_other_differences_being_sent(self):
        _, request, _, _ = self.request(FOUND, image="", rows=[row(MISMATCH, "Axle")])
        self.assertEqual([f["__self__"].rsplit("/", 1)[-1] for f in request["body"]["sections"][0]["fields"]], ["TITLE"])


class ComponentLinkTests(RunTestCase):
    LINKED = {"urn": "", "url": ""}

    def test_no_component_field_means_no_link(self):
        run = self.run_of(config=cfg(component_field=""))
        self.assertIsNone(run._component("PN-1", {"state": FOUND}, self.LINKED))

    def test_an_item_in_neither_state_gets_no_link(self):
        run = self.run_of(config=cfg("COMPONENT"))
        self.assertIsNone(run._component("PN-1", {"state": "error"}, self.LINKED))

    def test_the_link_the_data_model_gave_is_used_and_recorded(self):
        run = self.run_of(config=cfg("COMPONENT"))
        with mock.patch.object(runner, "manage_link", return_value="/api/v3/workspaces/1/items/9"):
            self.assertEqual(run._component("PN-1", {"state": NEW}, {"urn": "u", "url": "x"}), ("COMPONENT", "/api/v3/workspaces/1/items/9"))
        self.assertEqual(self.recorded("PN-1", "component link")[0]["status"], OK)

    def test_an_unlinked_component_is_looked_for_in_the_picklist(self):
        run = self.run_of(config=cfg("COMPONENT"))
        with mock.patch.object(runner, "ComponentService") as service:
            service.return_value.find.return_value = ("/api/v3/workspaces/1/items/7", "")
            self.assertEqual(run._component("PN-1", {"state": FOUND}, self.LINKED), ("COMPONENT", "/api/v3/workspaces/1/items/7"))

    def test_no_link_found_is_recorded_with_the_reason_and_the_item_goes_on(self):
        run = self.run_of(config=cfg("COMPONENT"))
        with mock.patch.object(runner, "ComponentService") as service:
            service.return_value.find.return_value = ("", "No such component.")
            self.assertIsNone(run._component("PN-1", {"state": FOUND}, self.LINKED))
        entry = self.recorded("PN-1", "component link")[0]
        self.assertEqual((entry["status"], entry["detail"]), (FAILED, "No such component."))

    def test_a_failed_search_for_the_component_is_the_reason(self):
        run = self.run_of(config=cfg("COMPONENT"))
        with mock.patch.object(runner, "ComponentService") as service:
            service.return_value.find.side_effect = FmApiError("503")
            self.assertIsNone(run._component("PN-1", {"state": FOUND}, self.LINKED))
        self.assertEqual(self.recorded("PN-1", "component link")[0]["detail"], "503")


class BomTests(RunTestCase):
    OPERATIONS = [{"op": "remove", "parent": "A", "number": "B", "sequence": 1, "edge": "9"}]

    def sending(self, **dispatcher):
        run = self.run_of(operations=self.OPERATIONS, send=True)
        run._dispatcher = mock.Mock(**dispatcher)
        return run, run._bom_row_of["A"], run._bom_requests["A"]

    def test_a_parents_requests_are_written_to_its_file(self):
        run = self.run_of(operations=self.OPERATIONS)
        run._write_boms()
        entry = self.recorded("A", "bom requests")[0]
        self.assertEqual((entry["status"], entry["detail"]), (OK, "1 request(s)"))
        with open(os.path.join(self.folder.path, "bom", "A.bom.request.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["parent"], "A")

    def test_no_bom_changes_is_recorded_as_skipped(self):
        run = self.run_of()
        run._write_boms()
        self.assertEqual(self.recorded("R", "bom requests")[0]["status"], SKIPPED)

    def test_a_parent_whose_requests_were_all_sent_is_done(self):
        run, bom_row, lines = self.sending(send_bom=mock.Mock(return_value="1 request(s) sent."))
        run._send_bom("A", lines)
        self.assertEqual((bom_row["status"], bom_row["detail"]), (DONE, "1 request(s) sent."))

    def test_a_parent_the_cancel_stopped_between_requests_is_cancelled(self):
        run, bom_row, lines = self.sending(send_bom=mock.Mock(return_value="Cancelled after 1 request(s)."))
        run._send_bom("A", lines)
        self.assertEqual(bom_row["status"], CANCELLED)

    def test_a_parent_that_failed_is_an_error_and_the_reason_is_recorded(self):
        run, bom_row, lines = self.sending(send_bom=mock.Mock(side_effect=FmApiError("Request 1 of 1: refused")))
        run._send_bom("A", lines)
        self.assertEqual((bom_row["status"], bom_row["detail"]), (ERROR, "Request 1 of 1: refused"))
        self.assertEqual(self.recorded("A", runner.SENT)[0]["status"], FAILED)

    def test_a_parent_cut_off_by_the_cancel_says_it_may_have_been_done(self):
        run, bom_row, lines = self.sending(send_bom=mock.Mock(side_effect=Cancelled()))
        run._send_bom("A", lines)
        self.assertEqual((bom_row["status"], bom_row["detail"]), (CANCELLED, CUT_OFF))

    def test_nothing_is_sent_for_a_parent_once_the_run_is_cancelled(self):
        run, bom_row, lines = self.sending(send_bom=mock.Mock())
        run.cancelled = True
        run._send_bom("A", lines)
        run._dispatcher.send_bom.assert_not_called()

    def test_the_progress_counts_requests_and_names_how_many_are_sent(self):
        def send(parent, lines, cancelled, progress):
            progress()
            return "done"

        run, bom_row, lines = self.sending(send_bom=send)
        run._send_bom("A", lines)
        self.assertEqual(run.snapshot()["bom"], {"done": 1, "total": 1})


class OutcomeTests(RunTestCase):
    """How a run ends is decided in one place, whatever the steps raise."""

    def outcome(self, run=None, **steps):
        run = run or self.run_of()
        with mock.patch.object(PublishRun, "_steps", **steps):
            return run._outcome()

    def test_steps_that_finish_end_the_run_done(self):
        self.assertEqual(self.outcome(), (DONE, ""))

    def test_a_run_cancelled_between_steps_ends_cancelled(self):
        run = self.run_of()
        run.cancelled = True
        self.assertEqual(self.outcome(run), (CANCELLED, "Cancelled."))

    def test_a_read_the_cancel_ended_ends_the_run_cancelled(self):
        self.assertEqual(self.outcome(side_effect=Cancelled()), (CANCELLED, "Cancelled."))

    def test_numbers_that_several_items_carry_end_the_run_with_the_reason(self):
        stopped = SharedItemNumbers({"PN-1": 2})
        self.assertEqual(self.outcome(side_effect=stopped), (ERROR, str(stopped)))

    def test_any_other_failure_ends_the_run_with_its_message_or_its_type(self):
        self.assertEqual(self.outcome(side_effect=FmApiError("down")), (ERROR, "down"))
        self.assertEqual(self.outcome(side_effect=KeyError()), (ERROR, "KeyError"))

    def test_work_ends_the_run_with_the_outcome_and_a_run_cancelled_while_waiting_never_starts(self):
        run = self.run_of()
        with mock.patch.object(PublishRun, "_steps", side_effect=FmApiError("down")):
            run.work()
        self.assertEqual((run.phase, run.message), (ERROR, "down"))
        waiting = self.run_of()
        waiting.cancel()
        with mock.patch.object(PublishRun, "_steps") as steps:
            waiting.work()
        steps.assert_not_called()


class StepsTests(RunTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(runner, "SectionService")   # the field sections are read from Fusion Manage
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_stages_run_in_order_and_the_bom_is_sent_last_when_sending(self):
        run = self.run_of(send=True)
        order = []
        with mock.patch.object(PublishRun, "_require_unique_numbers", lambda self, items: order.append("unique")), \
                mock.patch.object(PublishRun, "_write_boms", lambda self: order.append("write boms")), \
                mock.patch.object(PublishRun, "_send_boms", lambda self: order.append("send boms")):
            run._steps()
        self.assertEqual(order, ["unique", "write boms", "send boms"])
        self.assertEqual(run.stage, ITEMS)

    def test_a_run_that_only_writes_does_not_send_the_bom(self):
        run = self.run_of(send=False)
        with mock.patch.object(PublishRun, "_send_boms") as send:
            run._steps()
        send.assert_not_called()

    def test_a_cancelled_run_writes_and_sends_no_bom(self):
        run = self.run_of(send=True)
        run.cancelled = True
        with mock.patch.object(PublishRun, "_write_boms") as write, mock.patch.object(PublishRun, "_send_boms") as send:
            run._steps()
        write.assert_not_called()
        send.assert_not_called()

    def test_the_sections_are_read_while_the_item_numbers_are_checked_not_before_them(self):
        order, unique_began = [], threading.Event()

        def sections(_workspace_id):
            order.append("sections start")
            unique_began.wait(2)   # read first, it would wait here for a check that cannot begin until it is done
            order.append("sections end")
            return {"TITLE": "/s/1"}

        def unique(_self, _items):
            order.append("unique")
            unique_began.set()

        runner.SectionService.return_value.field_sections.side_effect = sections
        run = self.run_of()
        with mock.patch.object(PublishRun, "_require_unique_numbers", unique):
            run._steps()
        self.assertEqual(order, ["sections start", "unique", "sections end"])
        self.assertEqual(run._field_sections, {"TITLE": "/s/1"})

    def test_sections_that_cannot_be_read_stop_the_run_before_any_item_is_prepared(self):
        runner.SectionService.return_value.field_sections.side_effect = FmApiError("503")
        item = {"item_number": "PN-1", "id": "c1"}
        run = self.run_of([item])
        with mock.patch.object(PublishRun, "_require_unique_numbers"), mock.patch.object(PublishRun, "_prepare") as prepared:
            self.assertEqual(run._outcome(), (ERROR, "503"))
        prepared.assert_not_called()

    def test_a_run_with_no_workspace_reads_no_sections(self):
        run = self.run_of(config=cfg(workspace_id=""))
        with mock.patch.object(PublishRun, "_require_unique_numbers"):
            run._steps()
        runner.SectionService.assert_not_called()

    def test_how_long_the_start_took_is_logged(self):
        run = self.run_of()
        with mock.patch.object(PublishRun, "_require_unique_numbers"), self.assertLogs("MfgToFm.publish", "INFO") as logged:
            run._steps()
        text = "\n".join(logged.output)
        self.assertIn("The item numbers were checked in", text)
        self.assertIn("The sections of the workspace were read in", text)

    def test_numbers_that_are_not_unique_stop_the_steps_before_any_item_is_prepared(self):
        item = {"item_number": "PN-1", "id": "c1"}
        run = self.run_of([item])
        with mock.patch.object(PublishRun, "_require_unique_numbers", side_effect=SharedItemNumbers({"PN-1": 2})), \
                mock.patch.object(PublishRun, "_prepare") as prepared:
            with self.assertRaises(SharedItemNumbers):
                run._steps()
        prepared.assert_not_called()


class StateTests(RunTestCase):
    def test_a_run_that_failed_validating_is_unlisted_and_one_that_failed_later_is_not(self):
        run = self.run_of()
        self.assertEqual(run.stage, VALIDATING)
        run._end(ERROR, "x")
        self.assertTrue(run.unlisted)
        later = self.run_of()
        later._set(stage=ITEMS)
        later._end(ERROR, "x")
        self.assertFalse(later.unlisted)

    def test_the_snapshot_says_how_far_validating_and_the_bom_have_got(self):
        snapshot = self.run_of().snapshot()
        self.assertEqual(snapshot["validation"], {"done": 0, "total": 0, "counts": {}})
        self.assertEqual((snapshot["bom"], snapshot["kind"], snapshot["stage"]), ({"done": 0, "total": 0}, "publish", VALIDATING))

    def test_ending_saves_the_manifest_the_retry_reads(self):
        run = self.run_of()
        run._finish(DONE, "")
        with open(os.path.join(self.folder.path, "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual((manifest["root"], manifest["workspace_id"], manifest["tenant"], manifest["model"], manifest["cancelled"]),
                         ("R", "57", "acme", "m1|t1", False))
        self.assertEqual(run.phase, DONE)

    def test_a_row_left_running_when_the_run_ends_is_marked_not_left_running(self):
        item = {"item_number": "PN-1", "id": "c1"}
        run = self.run_of([item])
        run.rows[0]["status"] = RUNNING
        run._finish(ERROR, "broke")
        self.assertNotEqual(run.rows[0]["status"], RUNNING)


if __name__ == "__main__":
    unittest.main()

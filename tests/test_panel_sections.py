"""The sections the Publish panel asks for: one slot each, loaded on a worker thread, polled until done, and never cached past a reload."""

import threading
import time
import unittest
from unittest import mock

from src.config.models import ConnectionSettings
from src.config.workspace_models import ITEM_NUMBER_SOURCE, FieldMapping, WorkspaceConfig
from src.core.cancel import CancelToken, Cancelled
from src.publish import panel_sections
from src.publish.panel_sections import PublishSections
from tests.hub_fixtures import auth_of, capture

SUMMARY = {"component_id": "R", "composition": "RELEASED", "item_number": "TOP", "part_number": "TOP", "name": "Top", "description": "",
           "lineage": "urn:adsk.wipprod:dm.lineage:abc"}


class Fixture:
    """A ``PublishSections`` on stand-ins for everything it reaches out to; ``reads`` records what the Data Model was asked for."""

    def __init__(self, *, model=("m1", "t1"), summary=None, denied=""):
        self.model = model
        self.reads = []
        self.summary = SUMMARY if summary is None else summary
        self.gate = None   # a threading.Event a read waits for, so a test can look at a load that is still going
        self.config = config = mock.Mock(hub_id="hub1")
        config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant="acme")
        config.config.workspaces.get.return_value = WorkspaceConfig(workspace_id="242", mappings=[FieldMapping(ITEM_NUMBER_SOURCE, "NUMBER")])
        self.patches = [
            mock.patch.object(panel_sections, "FusionGraphQlClient"), mock.patch.object(panel_sections, "FmClient"),
            mock.patch.object(panel_sections, "ADDIN", mock.Mock(child=lambda *_: CancelToken())),   # real tokens: a replaced load is cancelled
            mock.patch.object(panel_sections, "MbomService"),
            mock.patch.object(panel_sections, "read_manage_item",
                              return_value={"urn": "urn:adsk.plm:tenant.workspace.item:ACME.57.16997", "url": ""}),
            mock.patch.object(panel_sections, "publish_denial", return_value=denied),
            mock.patch.object(panel_sections, "read_section", side_effect=self.read),
            mock.patch.object(panel_sections, "search_design", return_value=[]),
            mock.patch.object(panel_sections, "mark_design_bom", side_effect=lambda rows, *_: {"rows": rows, "shared": False}),
        ]
        for p in self.patches:
            p.start()
        self.auth = auth_of()
        self.sections = PublishSections(config, self.auth, lambda: self.model)

    def read(self, _client, section, _model_id, _time, summary, component_id="", _physical=False, _progress=None):
        self.reads.append((section, component_id, dict(summary or {})))
        if section == "structure" and _progress:
            _progress(2)   # a page of the structure was read
        if self.gate:
            self.gate.wait(5)
        if section == "summary":
            return dict(self.summary)
        if section == "structure":
            return [{"id": "c1", "level": 0, "item_number": "PN-1"}, {"id": "c2", "level": 1, "item_number": "PN-2"}]
        return {}

    def stop(self):
        for p in self.patches:
            p.stop()

    def wait(self, slot, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            snapshot = self.sections.status({"section": slot})
            if not snapshot["pending"]:
                return snapshot
            time.sleep(0.01)
        raise AssertionError(f"{slot} is still loading")

    def ask(self, section, **payload):
        return self.sections.request({"section": section, **payload})

    def ask_loaded(self, section):
        """Ask for a section after the summary, as the panel does, and wait for its answer."""
        self.ask("summary")
        self.wait("summary")
        self.ask(section)
        return self.wait(section)


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.stop)

    def test_a_section_is_pending_until_its_thread_is_done(self):
        self.fx.gate = threading.Event()
        first = self.fx.ask("summary")
        self.assertTrue(first["pending"])
        self.fx.gate.set()
        done = self.fx.wait("summary")
        self.assertTrue(done["ok"])
        self.assertEqual(done["data"]["item_number"], "TOP")

    def test_a_section_says_which_settings_it_was_read_under(self):
        stamp = capture(self.fx.config).stamp
        self.assertEqual(self.fx.ask("summary")["stamp"], stamp)
        self.assertEqual(self.fx.wait("summary")["stamp"], stamp)

    def test_a_loaded_section_is_read_again_when_the_tenant_or_workspace_changed_within_the_hub(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.config.config.workspaces.get.return_value = WorkspaceConfig(workspace_id="999")   # same hub and design, other workspace
        self.assertTrue(self.fx.ask("summary")["pending"])
        self.assertEqual(self.fx.wait("summary")["stamp"], capture(self.fx.config).stamp)
        self.assertEqual([r[0] for r in self.fx.reads].count("summary"), 2)

    def test_a_loaded_section_is_read_again_when_another_user_has_signed_in(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.auth.session.return_value = 2   # the same hub, tenant and workspace: a different sign-in
        self.assertTrue(self.fx.ask("summary")["pending"])
        self.fx.wait("summary")
        self.assertEqual([r[0] for r in self.fx.reads].count("summary"), 2)

    def test_a_loaded_section_is_kept_while_the_settings_are_unchanged(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.assertTrue(self.fx.ask("summary")["ok"])
        self.assertEqual([r[0] for r in self.fx.reads].count("summary"), 1)

    def test_what_a_load_read_under_old_settings_is_not_kept_when_a_newer_load_has_taken_its_slot(self):
        self.fx.gate = threading.Event()
        self.fx.ask("summary")
        self.fx.config.config.workspaces.get.return_value = WorkspaceConfig(workspace_id="999")
        self.fx.ask("summary")   # replaces the first load, which is still reading
        self.fx.gate.set()
        done = self.fx.wait("summary")
        self.assertEqual(done["stamp"], capture(self.fx.config).stamp)

    def test_a_load_reads_under_the_hub_it_was_asked_for_under_even_if_another_opens_meanwhile(self):
        self.fx.gate = threading.Event()
        stamp = capture(self.fx.config).stamp
        self.fx.ask("summary")
        self.fx.config.hub_id = "hub2"   # another hub is active before the load's thread has made its clients
        self.fx.config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant="other")
        self.fx.config.config.workspaces.get.return_value = WorkspaceConfig(workspace_id="999")
        self.fx.gate.set()
        done = self.fx.wait("summary")
        self.assertEqual(done["stamp"], stamp)
        self.assertEqual(panel_sections.FmClient.call_args[0][0].tenant, "acme")
        self.assertEqual(panel_sections.publish_denial.call_args[0][1].workspace_id, "242")

    def test_settings_that_cannot_be_read_are_the_answer_and_nothing_is_loaded(self):
        self.fx.config.effective_settings.side_effect = RuntimeError("share is down")
        answer = self.fx.ask("summary")
        self.assertEqual((answer["pending"], answer["message"]), (False, "share is down"))
        self.assertEqual(self.fx.reads, [])

    def test_asking_again_for_a_loaded_section_reads_nothing_unless_forced(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        again = self.fx.ask("summary")
        self.assertTrue(again["ok"])
        self.assertEqual(len(self.fx.reads), 1)
        self.fx.ask("summary", force=True)
        self.fx.wait("summary")
        self.assertEqual(len(self.fx.reads), 2)

    def test_the_mbom_tree_is_read_afresh_every_time_even_when_not_forced(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        with mock.patch.object(panel_sections, "BomService") as bom:
            bom.return_value.tree.return_value = {"number": "M-1", "children": []}
            for _ in range(2):
                self.fx.ask("mbom_tree", target="M-1", target_id="9")
                self.fx.wait("mbom_tree")
            self.assertEqual(bom.return_value.tree.call_count, 2)

    def test_another_design_is_read_afresh(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.assertEqual(len(self.fx.reads), 2)

    def test_the_structure_is_read_whole_at_once(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure")
        whole = self.fx.wait("structure")
        self.assertEqual([r["id"] for r in whole["data"]["rows"]], ["c1", "c2"])
        self.assertEqual([r[0] for r in self.fx.reads], ["summary", "structure"])

    def test_each_component_has_a_slot_of_its_own(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("thumbnail", id="A")
        self.fx.ask("thumbnail", id="B")
        a, b = self.fx.wait("thumbnail:A"), self.fx.wait("thumbnail:B")
        self.assertEqual((a["section"], b["section"]), ("thumbnail:A", "thumbnail:B"))
        self.assertTrue(a["ok"] and b["ok"])
        self.assertEqual(sorted(r[1] for r in self.fx.reads if r[0] == "thumbnail"), ["A", "B"])

    def test_a_summary_without_an_item_number_is_a_denial_not_an_error(self):
        fx = Fixture(summary={**SUMMARY, "item_number": ""})
        self.addCleanup(fx.stop)
        fx.ask("summary")
        done = fx.wait("summary")
        self.assertFalse(done["ok"])
        self.assertIn("no item number", done["denied"])

    def test_missing_permission_denies_the_summary_and_reads_nothing(self):
        fx = Fixture(denied="You may not publish")
        self.addCleanup(fx.stop)
        fx.ask("summary")
        done = fx.wait("summary")
        self.assertEqual(done["denied"], "You may not publish")
        self.assertEqual(fx.reads, [])

    def test_a_failing_read_is_reported_not_left_pending(self):
        panel_sections.read_section.side_effect = RuntimeError("down")
        self.fx.ask("summary")
        done = self.fx.wait("summary")
        self.assertFalse(done["ok"])
        self.assertEqual(done["message"], "down")

    def test_the_mbom_section_finds_the_items_made_from_the_open_design(self):
        found = [{"id": "11", "number": "PN-1-A"}]
        panel_sections.MbomService.return_value.find.return_value = found
        done = self.fx.ask_loaded("mbom")
        self.assertEqual((done["ok"], done["data"]), (True, found))
        panel_sections.MbomService.return_value.find.assert_called_once_with("242", "urn:adsk.wipprod:dm.lineage:abc",
                                                                             "/api/v3/workspaces/57/items/16997", "NUMBER")

    def test_a_failed_mbom_search_is_reported_not_an_empty_list(self):
        panel_sections.MbomService.return_value.find.side_effect = RuntimeError("no such field")
        done = self.fx.ask_loaded("mbom")
        self.assertEqual((done["ok"], done["message"]), (False, "no such field"))

    def test_an_unmapped_item_number_is_reported_not_searched(self):
        self.fx.config.config.workspaces.get.return_value = WorkspaceConfig(workspace_id="242")
        done = self.fx.ask_loaded("mbom")
        self.assertFalse(done["ok"])
        panel_sections.MbomService.return_value.find.assert_not_called()

    def test_a_design_with_no_record_in_the_components_workspace_is_reported_not_searched(self):
        panel_sections.read_manage_item.return_value = {"urn": "", "url": ""}
        done = self.fx.ask_loaded("mbom")
        self.assertFalse(done["ok"])
        self.assertTrue(done["message"])
        panel_sections.MbomService.return_value.find.assert_not_called()

    def test_a_section_that_compares_the_design_uses_the_item_number_of_the_target(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure", target="MBOM-2")
        self.fx.wait("structure")
        self.assertEqual(panel_sections.search_design.call_args.args[2]["item_number"], "MBOM-2")
        self.fx.ask("structure")
        self.fx.wait("structure")
        self.assertEqual(panel_sections.search_design.call_args.args[2]["item_number"], "TOP")

    def test_a_target_with_an_item_id_is_read_by_the_id_not_searched_for_by_its_number(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure", target="MBOM-2", target_id="55")
        done = self.fx.wait("structure")
        self.assertEqual(done["target_id"], "55")
        panel_sections.search_design.assert_not_called()
        self.assertEqual(panel_sections.mark_design_bom.call_args.args[2], [{"id": "55"}])

    def test_a_target_without_an_item_id_is_searched_for_by_its_number(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure", target="NEW-1")
        self.fx.wait("structure")
        panel_sections.search_design.assert_called_once()

    def structure_reads(self):
        return [r for r in self.fx.reads if r[0] == "structure"]

    def test_another_target_is_marked_afresh_and_the_same_one_is_kept(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        for target in ("A", "A", "B"):
            self.fx.ask("structure", target=target)
            self.fx.wait("structure")
        self.assertEqual(panel_sections.mark_design_bom.call_count, 2)

    def test_the_same_number_with_another_item_id_is_marked_afresh(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        for item_id in ("55", "55", "56"):
            self.fx.ask("structure", target="MBOM-2", target_id=item_id)
            self.fx.wait("structure")
        self.assertEqual(panel_sections.mark_design_bom.call_count, 2)

    def test_another_target_does_not_read_the_data_model_again(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        for target, target_id in (("", ""), ("A", "1"), ("B", "2"), ("A", "1")):
            self.fx.ask("structure", target=target, target_id=target_id)
            done = self.fx.wait("structure")
            self.assertEqual([r["id"] for r in done["data"]["rows"]], ["c1", "c2"])
        self.assertEqual(len(self.structure_reads()), 1)
        self.assertEqual(panel_sections.mark_design_bom.call_count, 4, "what depends on the target is worked out each time")

    def test_a_forced_structure_is_read_again_and_then_kept(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure")
        self.fx.wait("structure")
        self.fx.ask("structure", force=True)
        self.fx.wait("structure")
        self.assertEqual(len(self.structure_reads()), 2)
        self.fx.ask("structure", target="B")
        self.fx.wait("structure")
        self.assertEqual(len(self.structure_reads()), 2)

    def test_another_design_reads_the_structure_again_and_the_first_is_not_kept(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure")
        self.fx.wait("structure")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure")
        self.fx.wait("structure")
        self.fx.model = ("m1", "t1")
        self.fx.ask("structure", target="B")
        self.fx.wait("structure")
        self.assertEqual(len(self.structure_reads()), 3)

    def test_the_rows_of_a_design_are_dropped_as_soon_as_another_is_open(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure")
        self.fx.wait("structure")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")
        self.assertIsNone(self.fx.sections._rows, "a large structure is not held for a design that is no longer open")
        self.fx.wait("summary")

    def test_the_structure_is_read_again_under_other_settings(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure")
        self.fx.wait("structure")
        self.fx.config.config.workspaces.get.return_value = WorkspaceConfig(workspace_id="999")   # same hub and design, other workspace
        self.fx.ask("structure", target="B")
        self.fx.wait("structure")
        self.assertEqual(len(self.structure_reads()), 2)

    def test_a_load_that_was_replaced_keeps_nothing(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.gate = threading.Event()
        self.fx.ask("structure", target="A")
        end = time.time() + 5
        while not self.structure_reads() and time.time() < end:
            time.sleep(0.01)
        self.fx.sections._tokens["structure"].cancel()   # what a newer load of the slot does to the one before it
        self.fx.gate.set()
        self.fx.wait("structure")
        self.fx.ask("structure", target="B")
        self.fx.wait("structure")
        self.assertEqual(len(self.structure_reads()), 2, "the read that was cancelled was not kept for the next")

    def test_the_progress_of_the_first_read_is_told_while_it_runs(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.gate = threading.Event()
        self.fx.ask("structure")
        end = time.time() + 5
        while time.time() < end and self.fx.sections.status({"section": "structure"})["progress"] != 2:
            time.sleep(0.01)
        snapshot = self.fx.sections.status({"section": "structure"})
        self.assertTrue(snapshot["pending"])
        self.assertEqual(snapshot["progress"], 2)
        self.fx.gate.set()
        self.fx.wait("structure")

    def test_the_other_slots_of_the_design_are_left_alone_by_another_target(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("thumbnail", id="c1")
        self.fx.wait("thumbnail:c1")
        self.fx.ask("structure", target="A")
        self.fx.wait("structure")
        self.assertTrue(self.fx.sections.status({"section": "thumbnail:c1"})["ok"])

    def test_the_number_check_asks_whether_the_item_number_it_is_given_is_taken(self):
        panel_sections.MbomService.return_value.number_taken.return_value = True
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("mbom_number", target="101-00001-B")
        done = self.fx.wait("mbom_number")
        self.assertEqual((done["ok"], done["data"], done["target"]), (True, {"taken": True}, "101-00001-B"))
        panel_sections.MbomService.return_value.number_taken.assert_called_once_with("242", "101-00001-B")

    def test_each_number_is_checked_afresh(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        for number in ("101-00001-B", "101-00001-C"):
            self.fx.ask("mbom_number", target=number)
            self.fx.wait("mbom_number")
        self.assertEqual(panel_sections.MbomService.return_value.number_taken.call_count, 2)

    def test_a_section_that_does_not_compare_the_design_ignores_the_target(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.assertEqual(self.fx.ask("thumbnail", target="A")["target"], "")

    def test_a_load_replaced_by_a_newer_one_leaves_the_slot_to_it(self):
        panel_sections.read_section.side_effect = [Cancelled(), dict(SUMMARY)]
        self.fx.ask("summary")
        time.sleep(0.1)   # the first thread ends without writing
        self.assertTrue(self.fx.sections.status({"section": "summary"})["pending"])
        self.fx.ask("summary", force=True)
        self.assertTrue(self.fx.wait("summary")["ok"])

    def test_an_answer_for_a_design_no_longer_open_is_ignored(self):
        self.fx.gate = threading.Event()
        self.fx.ask("summary")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")   # the other design takes the slot while the first read is still going
        self.fx.gate.set()
        done = self.fx.wait("summary")
        self.assertEqual(done["key"], "m2|t1")

    def test_the_slots_of_components_of_another_design_are_dropped(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("thumbnail", id="A")
        self.fx.wait("thumbnail:A")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.assertEqual(self.fx.sections.status({"section": "thumbnail:A"})["pending"], False)
        self.assertIn("Unknown section", self.fx.sections.status({"section": "thumbnail:A"})["message"])
        self.assertNotIn("thumbnail:A", self.fx.sections._slots)

    def test_a_load_whose_slot_was_dropped_ends_quietly(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.gate = threading.Event()
        self.fx.ask("thumbnail", id="A")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")   # drops thumbnail:A while its read is still going
        self.fx.gate.set()
        self.fx.wait("summary")
        time.sleep(0.1)   # the dropped load finishes, and finds nothing waiting for it
        self.assertNotIn("thumbnail:A", self.fx.sections._slots)

    def test_a_failure_making_the_clients_is_reported_not_left_pending(self):
        panel_sections.FmClient.side_effect = RuntimeError("no settings")
        self.fx.ask("summary")
        done = self.fx.wait("summary")
        self.assertEqual((done["ok"], done["message"]), (False, "no settings"))

    def test_a_design_that_cannot_be_asked_for_is_an_answer_not_a_crash(self):
        fx = Fixture()
        self.addCleanup(fx.stop)
        fx.sections._model_ref = mock.Mock(side_effect=RuntimeError("no design"))
        self.assertEqual(fx.ask("summary")["message"], "no design")

    def test_an_unknown_section_and_no_open_design_are_answers_not_crashes(self):
        self.assertIn("Unknown section", self.fx.ask("nope")["message"])
        fx = Fixture(model=("", ""))
        self.addCleanup(fx.stop)
        self.assertIn("Data Model id", fx.ask("summary")["message"])


if __name__ == "__main__":
    unittest.main()

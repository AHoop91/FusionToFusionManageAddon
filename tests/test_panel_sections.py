"""The sections the Publish panel asks for: one slot each, loaded on a worker thread, polled until done, and never cached past a reload."""

import threading
import time
import unittest
from unittest import mock

from src.config.models import ConnectionSettings
from src.config.workspace_models import WorkspaceConfig
from src.core.cancel import Cancelled
from src.publish import panel_sections
from src.publish.panel_sections import PublishSections
from tests.hub_fixtures import auth_of, capture

SUMMARY = {"component_id": "R", "composition": "RELEASED", "item_number": "TOP", "part_number": "TOP", "name": "Top", "description": ""}


class Fixture:
    """A ``PublishSections`` on stand-ins for everything it reaches out to; ``reads`` records what the Data Model was asked for."""

    def __init__(self, *, model=("m1", "t1"), summary=None, denied=""):
        self.model = model
        self.reads = []
        self.summary = SUMMARY if summary is None else summary
        self.gate = None   # a threading.Event a read waits for, so a test can look at a load that is still going
        self.config = config = mock.Mock(hub_id="hub1")
        config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant="acme")
        config.config.workspaces.get.return_value = WorkspaceConfig(workspace_id="242")
        self.patches = [
            mock.patch.object(panel_sections, "FusionGraphQlClient"), mock.patch.object(panel_sections, "FmClient"),
            mock.patch.object(panel_sections, "ADDIN"),
            mock.patch.object(panel_sections, "publish_denial", return_value=denied),
            mock.patch.object(panel_sections, "read_section", side_effect=self.read),
            mock.patch.object(panel_sections, "search_design", return_value=[]),
            mock.patch.object(panel_sections, "compare_design_bom", side_effect=lambda rows, *_: {"rows": rows, "shared": False}),
            mock.patch.object(panel_sections, "compare_level", side_effect=lambda rows, *_: {"rows": rows}),
        ]
        for p in self.patches:
            p.start()
        self.auth = auth_of()
        self.sections = PublishSections(config, self.auth, lambda: self.model)

    def read(self, _client, section, _model_id, _time, summary, component_id="", _physical=False, _progress=None):
        self.reads.append((section, component_id, dict(summary or {})))
        if self.gate:
            self.gate.wait(5)
        if section == "summary":
            return dict(self.summary)
        if section == "level":
            return [{"id": "c1", "level": 0, "item_number": "PN-1"}]
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

    def test_another_design_is_read_afresh(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.assertEqual(len(self.fx.reads), 2)

    def test_the_first_level_is_one_level_and_the_tree_is_the_whole(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("structure")
        self.fx.ask("tree")
        top, whole = self.fx.wait("structure"), self.fx.wait("tree")
        self.assertEqual([r["id"] for r in top["data"]["rows"]], ["c1"])
        self.assertEqual([r["id"] for r in whole["data"]["rows"]], ["c1", "c2"])
        self.assertEqual({r[0] for r in self.fx.reads}, {"summary", "level", "structure"})

    def test_each_assembly_has_a_slot_of_its_own(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("children", id="A", item_number="PN-A", compared="1")
        self.fx.ask("children", id="B", item_number="PN-B", compared="1")
        a, b = self.fx.wait("children:A"), self.fx.wait("children:B")
        self.assertEqual((a["section"], b["section"]), ("children:A", "children:B"))
        self.assertTrue(a["ok"] and b["ok"])
        self.assertEqual(sorted(r[1] for r in self.fx.reads if r[0] == "level"), ["A", "B"])

    def test_a_children_load_carries_what_the_comparison_needs(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.ask("children", id="A", item_number="PN-A", skip="1", compared="1")
        self.fx.wait("children:A")
        args = panel_sections.compare_level.call_args[0]
        self.assertEqual(args[1:4], ("PN-A", True, True))

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
        self.fx.ask("children", id="A", item_number="PN-A")
        self.fx.wait("children:A")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.assertEqual(self.fx.sections.status({"section": "children:A"})["pending"], False)
        self.assertIn("Unknown section", self.fx.sections.status({"section": "children:A"})["message"])
        self.assertNotIn("children:A", self.fx.sections._slots)

    def test_a_load_whose_slot_was_dropped_ends_quietly(self):
        self.fx.ask("summary")
        self.fx.wait("summary")
        self.fx.gate = threading.Event()
        self.fx.ask("children", id="A", item_number="PN-A")
        self.fx.model = ("m2", "t1")
        self.fx.ask("summary")   # drops children:A while its read is still going
        self.fx.gate.set()
        self.fx.wait("summary")
        time.sleep(0.1)   # the dropped load finishes, and finds nothing waiting for it
        self.assertNotIn("children:A", self.fx.sections._slots)

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

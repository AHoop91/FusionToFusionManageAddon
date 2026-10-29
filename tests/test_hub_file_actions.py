"""Finding the hub's Configuration File, reading it as the settings and keeping up with it. Run: python -m unittest discover tests"""

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from src.config.config_envelope import ConfigTransferError
from src.core.cancel import Cancelled
from src.fusion_mfg.fusion_hub_files import HubFilesError
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import hub_file_actions
    from src.ui.actions.hub_file_actions import (NO_FILE_CHOSEN, NO_HUB, START_WAIT_TRIES, HubConfigFile, _Job,
                                                 register_hub_file_actions)
    from src.ui.message_bridge import MessageBridge

KEPT = {"project_id": "p1", "item_id": "i1", "name": "hub.json", "modified": "2024-01-01", "version": "3"}


def listing(folders=(), files=()):
    return SimpleNamespace(folders=list(folders), files=list(files))


class Setup(unittest.TestCase):
    def setUp(self):
        self.config = mock.Mock()
        self.config.hub_id, self.config.hub_name = "hub-1", "Hub One"
        self.config.config.hub_file = dict(KEPT)
        self.config.apply_hub_file.return_value = []
        self.hub = mock.Mock()
        self.hub.file_info.return_value = {"modified": "2024-01-01", "version": "3", "modified_by": "Ada"}
        self.hub.read_file.return_value = b"raw"
        self.file = HubConfigFile(self.config, lambda: self.hub)
        for patch in (mock.patch.object(hub_file_actions, "config_from_hub_file", return_value="imported"),
                      mock.patch.object(hub_file_actions, "settings_payload", return_value={"shown": True})):
            patch.start()
            self.addCleanup(patch.stop)


class BrowseTests(Setup):
    def test_no_project_lists_the_projects(self):
        self.hub.projects.return_value = listing([{"id": "p1"}])
        self.assertEqual(self.file.browse("", ""), {"folders": [{"id": "p1"}], "files": []})

    def test_a_project_with_several_top_folders_lists_them(self):
        self.hub.top_folders.return_value = listing([{"id": "a"}, {"id": "b"}])
        self.assertEqual(self.file.browse("p1", "")["folders"], [{"id": "a"}, {"id": "b"}])

    def test_a_project_with_one_top_folder_shows_what_is_in_it(self):
        self.hub.top_folders.return_value = listing([{"id": "root"}])
        self.hub.contents.return_value = listing([{"id": "sub"}], [{"id": "f"}])
        self.assertEqual(self.file.browse("p1", ""), {"folders": [{"id": "sub"}], "files": [{"id": "f"}], "folder_id": "root"})
        self.hub.contents.assert_called_once_with("root")

    def test_a_folder_lists_its_contents(self):
        self.hub.contents.return_value = listing(files=[{"id": "f"}])
        self.assertEqual(self.file.browse("p1", "fo"), {"folders": [], "files": [{"id": "f"}]})
        self.hub.contents.assert_called_once_with("fo")


class ApplyTests(Setup):
    def apply(self):
        return self.file.apply("hub-1", "Hub One", "p1", "i1", "hub.json")

    def test_the_file_becomes_the_settings_with_where_it_came_from(self):
        self.assertEqual(self.apply(), {"settings": {"shown": True}})
        imported, ref = self.config.apply_hub_file.call_args[0]
        self.assertEqual(imported, "imported")
        self.assertEqual((ref["project_id"], ref["item_id"], ref["name"]), ("p1", "i1", "hub.json"))
        self.assertEqual((ref["modified"], ref["modified_by"]), ("2024-01-01", "Ada"))
        self.assertTrue(ref["read_at"])

    def test_details_the_hub_will_not_give_do_not_stop_it(self):
        self.hub.file_info.side_effect = HubFilesError("no details")
        self.apply()
        ref = self.config.apply_hub_file.call_args[0][1]
        self.assertNotIn("modified", ref)

    def test_a_change_of_hub_while_the_file_is_read_is_refused(self):
        self.hub.read_file.side_effect = lambda *args: setattr(self.config, "hub_id", "hub-2") or b"raw"
        with self.assertRaises(HubFilesError):
            self.apply()
        self.config.apply_hub_file.assert_not_called()

    def test_settings_that_are_not_valid_are_refused_with_why(self):
        self.config.apply_hub_file.return_value = ["bad one", "bad two"]
        with self.assertRaisesRegex(ConfigTransferError, "bad one bad two"):
            self.apply()


class PlanApplyTests(Setup):
    def test_the_chosen_file_is_read_in_the_hub_open_now(self):
        with mock.patch.object(self.file, "apply") as apply:
            self.file.plan_apply({"project_id": "p2", "item_id": "i2", "name": "other.json"})()
        apply.assert_called_once_with("hub-1", "Hub One", "p2", "i2", "other.json")

    def test_without_a_choice_the_file_the_settings_came_from_is_read_again(self):
        with mock.patch.object(self.file, "apply") as apply:
            self.file.plan_apply({})()
        apply.assert_called_once_with("hub-1", "Hub One", "p1", "i1", "hub.json")

    def test_no_hub_is_refused(self):
        self.config.hub_id = ""
        with self.assertRaisesRegex(ValueError, NO_HUB):
            self.file.plan_apply({})

    def test_no_file_is_refused(self):
        self.config.config.hub_file = None
        with self.assertRaisesRegex(ValueError, NO_FILE_CHOSEN):
            self.file.plan_apply({})


class CheckTests(Setup):
    def test_no_file_kept_or_no_hub_is_none(self):
        self.config.config.hub_file = None
        self.assertEqual(self.file.check(), {"state": "none"})
        self.config.config.hub_file, self.config.hub_id = dict(KEPT), ""
        self.assertEqual(self.file.check(), {"state": "none"})
        self.hub.file_info.assert_not_called()

    def test_a_file_as_it_was_is_current(self):
        found = self.file.check()
        self.assertEqual((found["state"], bool(found["checked_at"])), ("current", True))
        self.config.apply_hub_file.assert_not_called()

    def test_a_file_that_changed_is_read_again_and_says_who_changed_it(self):
        self.hub.file_info.return_value = {"modified": "2024-02-02", "version": "4", "modified_by": "Grace"}
        found = self.file.check()
        self.assertEqual((found["state"], found["by"], found["settings"]), ("updated", "Grace", {"shown": True}))
        self.config.apply_hub_file.assert_called_once()

    def test_a_version_change_alone_counts(self):
        self.hub.file_info.return_value = {"modified": "2024-01-01", "version": "4"}
        self.assertEqual(self.file.check()["state"], "updated")

    def test_a_hub_that_says_nothing_of_the_file_is_unknown(self):
        self.hub.file_info.return_value = {}
        found = self.file.check()
        self.assertEqual(found["state"], "unknown")
        self.assertIn("did not say", found["message"])
        self.config.apply_hub_file.assert_not_called()

    def test_a_failure_of_the_hub_is_unknown_with_why(self):
        self.hub.file_info.side_effect = HubFilesError("hub down")
        found = self.file.check()
        self.assertEqual((found["state"], found["message"]), ("unknown", "hub down"))

    def test_an_unexpected_failure_is_unknown_and_never_raised(self):
        self.hub.file_info.side_effect = RuntimeError()
        found = self.file.check()
        self.assertEqual((found["state"], found["message"]), ("unknown", "RuntimeError"))

    def test_a_file_that_changed_but_cannot_be_read_is_unknown_with_why(self):
        self.hub.file_info.return_value = {"modified": "2024-02-02", "version": "4"}
        self.hub.read_file.side_effect = HubFilesError("cannot read")
        found = self.file.check()
        self.assertEqual((found["state"], found["message"]), ("unknown", "cannot read"))


class CheckAtStartTests(Setup):
    def setUp(self):
        super().setUp()
        self.bridge = mock.Mock()

    def test_a_file_that_changed_is_pushed_for_the_panel(self):
        self.hub.file_info.return_value = {"modified": "new", "version": "4"}
        self.file.check_at_start(self.bridge, wait=mock.Mock())
        self.assertEqual(self.bridge.push.call_args[0][0], "hub_file_checked")
        self.assertEqual(self.bridge.push.call_args[0][1]["state"], "updated")

    def test_a_file_that_is_current_pushes_nothing(self):
        self.file.check_at_start(self.bridge, wait=mock.Mock())
        self.bridge.push.assert_not_called()

    def test_it_waits_for_the_hub_to_open_then_checks(self):
        self.config.hub_id = ""
        wait = mock.Mock(side_effect=lambda seconds: setattr(self.config, "hub_id", "hub-1"))
        self.hub.file_info.return_value = {}
        self.file.check_at_start(self.bridge, wait=wait)
        wait.assert_called_once()
        self.assertEqual(self.bridge.push.call_args[0][1]["state"], "unknown")

    def test_it_gives_up_when_there_is_never_a_hub_or_a_file(self):
        self.config.config.hub_file = None
        wait = mock.Mock()
        self.file.check_at_start(self.bridge, wait=wait)
        self.assertEqual(wait.call_count, START_WAIT_TRIES)
        self.bridge.push.assert_not_called()

    def test_it_stops_quietly_when_the_add_in_stops(self):
        self.config.config.hub_file = None
        self.file.check_at_start(self.bridge, wait=mock.Mock(side_effect=Cancelled()))
        self.bridge.push.assert_not_called()


class JobTests(unittest.TestCase):
    def setUp(self):
        self.bridge = mock.Mock()
        self.queued = []
        self.job = _Job(self.bridge, "act", run=self.queued.append)

    def finish(self):
        while self.queued:
            self.queued.pop(0)()

    def test_a_start_answers_pending_and_the_outcome_is_pushed_when_done(self):
        started = self.job.start(lambda: {"folders": []})
        self.assertEqual((started["pending"], started["id"]), (True, 1))
        self.finish()
        pushed = self.bridge.push.call_args[0]
        self.assertEqual(pushed[0], "act")
        self.assertEqual((pushed[1]["ok"], pushed[1]["pending"], pushed[1]["folders"]), (True, False, []))
        self.assertEqual(self.job.status()["pending"], False)

    def test_a_failure_with_a_reason_is_told_as_it_is(self):
        def fail():
            raise HubFilesError("hub down")
        self.job.start(fail)
        self.finish()
        self.assertEqual((self.job.status()["ok"], self.job.status()["message"]), (False, "hub down"))

    def test_an_unexpected_failure_is_told_by_its_kind_when_it_has_no_message(self):
        def fail():
            raise RuntimeError()
        self.job.start(fail)
        self.finish()
        self.assertEqual(self.job.status()["message"], "RuntimeError")

    def test_a_newer_request_replaces_an_older_one_whose_answer_is_dropped(self):
        self.job.start(lambda: {"which": "old"})
        self.job.start(lambda: {"which": "new"})
        self.finish()
        self.assertEqual(self.bridge.push.call_count, 1)
        self.assertEqual(self.bridge.push.call_args[0][1]["which"], "new")
        self.assertEqual(self.job.status()["id"], 2)

    def test_a_runner_that_does_the_work_at_once_does_not_deadlock(self):
        job = _Job(self.bridge, "act", run=lambda work: work())
        done = []
        thread = threading.Thread(target=lambda: done.append(job.start(lambda: {})), daemon=True)
        thread.start()
        thread.join(5)
        self.assertEqual(len(done), 1)
        self.assertEqual(job.status()["pending"], False)


class RegisterTests(unittest.TestCase):
    def test_every_action_is_registered_and_a_browse_without_a_hub_is_refused(self):
        bridge = MessageBridge()
        config = mock.Mock()
        config.hub_id = ""
        with mock.patch.object(hub_file_actions, "in_thread"):   # no start-up check on a thread of its own
            register_hub_file_actions(bridge, config, mock.Mock())
        for action in ("browse_hub_files", "use_hub_config", "check_hub_file"):
            self.assertEqual(bridge.dispatch(f"{action}_status", "")["result"]["pending"], False)
        reply = bridge.dispatch("browse_hub_files", "{}")
        self.assertEqual((reply["ok"], reply["error"]), (False, NO_HUB))
        reply = bridge.dispatch("use_hub_config", "{}")
        self.assertEqual((reply["ok"], reply["error"]), (False, NO_HUB))


if __name__ == "__main__":
    unittest.main()

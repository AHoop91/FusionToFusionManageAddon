"""Queueing, retrying and listing publish runs, and telling the user how a run ended. Run: python -m unittest discover tests"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from src.fm.client import FmApiError
from src.publish.sender import FolderError
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import publish_run_actions
    from src.ui.actions.publish_run_actions import Announcement, PublishRuns, announcement, register_publish_run_actions
    from src.ui.message_bridge import MessageBridge


def finished(kind, phase, failed_rows=0, run_id="r1"):
    rows = [{"status": "error"}] * failed_rows + [{"status": "done"}]
    return SimpleNamespace(id=run_id, kind=kind, phase=phase, rows=rows, path="/runs/r1")


class Reports(unittest.TestCase):
    """The reports are written by ``publish.reports``; here they are stand-ins that note whether they were written."""

    def setUp(self):
        self.cut_off = mock.Mock(return_value=False)
        self.publish_report = mock.Mock(return_value="PUBLISH REPORT")
        self.send_report = mock.Mock(return_value="SEND REPORT")
        for patch in (mock.patch.object(publish_run_actions, "publish_report", self.publish_report),
                      mock.patch.object(publish_run_actions, "send_report", self.send_report),
                      mock.patch.object(publish_run_actions, "cut_off", self.cut_off)):
            patch.start()
            self.addCleanup(patch.stop)


class AnnouncementTests(Reports):
    def test_no_report_is_written_for_a_run_there_is_nothing_to_say_of(self):
        announcement(finished("publish", "cancelled"))
        announcement(finished("send", "running"))
        self.publish_report.assert_not_called()
        self.send_report.assert_not_called()

    def test_a_publish_that_went_well_is_a_note(self):
        self.assertEqual(announcement(finished("publish", "done")), Announcement(False, "PUBLISH REPORT", "Publish complete"))

    def test_a_publish_that_had_failed_items_is_a_warning(self):
        self.assertEqual(announcement(finished("publish", "done", failed_rows=1)),
                         Announcement(True, "PUBLISH REPORT", "Publish completed with errors"))

    def test_a_publish_that_failed_is_a_warning(self):
        self.assertEqual(announcement(finished("publish", "error")), Announcement(True, "PUBLISH REPORT", "Publish failed"))

    def test_a_send_that_went_well_is_a_note(self):
        self.assertEqual(announcement(finished("send", "done")), Announcement(False, "SEND REPORT", "Sent to Fusion Manage"))

    def test_a_send_that_failed_or_had_failed_items_is_a_warning(self):
        for run in (finished("send", "error"), finished("send", "done", failed_rows=2)):
            self.assertEqual(announcement(run), Announcement(True, "SEND REPORT", "Send to Fusion Manage failed"))

    def test_a_run_the_user_stopped_says_nothing(self):
        self.assertIsNone(announcement(finished("publish", "cancelled")))
        self.assertIsNone(announcement(finished("send", "cancelled")))

    def test_a_run_stopped_with_a_request_cut_off_warns_that_it_may_have_been_done(self):
        self.cut_off.return_value = True
        self.assertEqual(announcement(finished("publish", "cancelled")),
                         Announcement(True, "PUBLISH REPORT", "Cancelled: some requests may have been done"))
        self.assertEqual(announcement(finished("send", "cancelled"))[1], "SEND REPORT")

    def test_a_run_that_has_not_ended_says_nothing(self):
        self.assertIsNone(announcement(finished("publish", "running")))


class Setup(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.bridge = mock.Mock()
        self.config = mock.Mock()
        self.dialogs, self.alerts = mock.Mock(), mock.Mock()
        self.ref = mock.Mock(return_value=("m1", "t1"))
        self.queued = []   # permission checks, run by the test when it wants them to
        self.runs = PublishRuns(self.bridge, self.config, mock.Mock(), self.dialogs, mock.Mock(), self.alerts, self.ref,
                                self.queued.append, self.root.name)
        self.runs.queue = mock.Mock()
        self.runs.queue.snapshots.return_value = [{"id": "r0"}]
        self.items_kind = publish_run_actions.ITEMS_KIND
        self.config.config.workspaces = {self.items_kind: SimpleNamespace(workspace_id="242")}
        self.run = SimpleNamespace(id="r1")
        self.denial = mock.Mock(return_value="")
        for patch in (mock.patch.object(publish_run_actions, "FmClient"),
                      mock.patch.object(publish_run_actions, "FusionGraphQlClient"),
                      mock.patch.object(publish_run_actions, "PublishRun", return_value=self.run),
                      mock.patch.object(publish_run_actions, "publish_denial", self.denial)):
            patch.start()
            self.addCleanup(patch.stop)

    def finish_checks(self):
        while self.queued:
            self.queued.pop(0)()


class StartTests(Setup):
    def test_without_the_items_workspace_it_says_so_and_checks_nothing(self):
        self.config.config.workspaces = {}
        self.assertEqual(self.runs.start({}), {"error": "Set the Items workspace ID in Settings first."})
        self.config.config.workspaces = {self.items_kind: SimpleNamespace(workspace_id="")}
        self.assertIn("error", self.runs.start({}))
        self.assertEqual(self.queued, [])

    def test_without_a_saved_design_it_says_so_and_checks_nothing(self):
        self.ref.return_value = ("", "")
        self.assertEqual(self.runs.start({}), {"error": "Could not find the Data Model id of the open design."})
        self.assertEqual(self.queued, [])

    def test_it_answers_at_once_that_it_is_checking_and_the_check_runs_apart(self):
        self.assertEqual(self.runs.start({"root_number": "TOP"}), {"checking": True})
        self.denial.assert_not_called()
        self.assertEqual(len(self.queued), 1)

    def test_a_publish_that_may_go_ahead_is_queued_and_the_panel_told(self):
        payload = {"summary": {"a": 1}, "items": [{"n": 1}], "operations": [], "root_number": "TOP"}
        self.runs.start(payload)
        self.finish_checks()
        self.runs.queue.add.assert_called_once_with(self.run)
        self.bridge.push.assert_called_once_with("start_publish_result", {"queued": "r1", "jobs": [{"id": "r0"}]})
        self.assertTrue(self.runs._watched.following("r1"))   # the panel's progress dialog follows it
        job = publish_run_actions.PublishRun.call_args[0][1]
        self.assertEqual((job["summary"], job["items"], job["root_number"]), ({"a": 1}, [{"n": 1}], "TOP"))
        folders = os.listdir(self.root.name)   # its folder was made
        self.assertEqual(len(folders), 1)
        self.assertTrue(folders[0].startswith("TOP_"), folders)

    def test_a_denied_publish_is_told_and_leaves_no_folder(self):
        self.denial.return_value = "You may not publish."
        self.runs.start({"root_number": "TOP"})
        self.finish_checks()
        self.bridge.push.assert_called_once_with("start_publish_result", {"error": "You may not publish."})
        self.runs.queue.add.assert_not_called()
        self.assertEqual(os.listdir(self.root.name), [])

    def test_permissions_that_could_not_be_checked_are_told_with_why(self):
        self.denial.side_effect = FmApiError("down", 503)
        self.runs.start({})
        self.finish_checks()
        self.assertEqual(self.bridge.push.call_args[0][1], {"error": "Could not check your permissions in Fusion Manage: down"})

    def test_a_failure_before_the_folder_is_made_leaves_no_folder(self):
        publish_run_actions.FusionGraphQlClient.side_effect = RuntimeError("no Data Model")
        self.runs.start({"root_number": "TOP"})
        self.finish_checks()
        self.assertEqual(self.bridge.push.call_args[0][1], {"error": "no Data Model"})
        self.assertEqual(os.listdir(self.root.name), [])
        self.runs.queue.add.assert_not_called()

    def test_a_failure_is_told_by_its_kind_when_it_has_no_message(self):
        self.config.effective_settings.side_effect = RuntimeError()
        self.runs.start({})
        self.finish_checks()
        self.assertEqual(self.bridge.push.call_args[0][1], {"error": "RuntimeError"})


class RetryTests(Setup):
    def test_a_run_that_is_not_listed_or_not_ended_is_left_alone(self):
        self.runs.queue.get.return_value = None
        self.assertEqual(self.runs.retry({"id": "x"}), {"jobs": [{"id": "r0"}]})
        self.runs.queue.get.return_value = finished("send", "running")
        self.runs.retry({"id": "r1"})
        self.runs.queue.replace.assert_not_called()

    def test_a_failed_run_is_queued_again_in_its_place(self):
        failed = finished("send", "error")
        self.runs.queue.get.return_value = failed
        with mock.patch.object(publish_run_actions, "load_plan", return_value="plan"), \
                mock.patch.object(publish_run_actions, "SendRun") as send:
            self.runs.retry({"id": "r1"})
        send.assert_called_once()
        self.assertEqual(send.call_args[0][:2], ("/runs/r1", "plan"))
        self.runs.queue.replace.assert_called_once_with(failed, send.return_value)

    def test_a_folder_that_cannot_be_sent_is_told_to_the_user_and_not_queued(self):
        self.runs.queue.get.return_value = finished("send", "error")
        with mock.patch.object(publish_run_actions, "load_plan", side_effect=FolderError("files are gone")):
            self.assertEqual(self.runs.retry({"id": "r1"}), {"jobs": [{"id": "r0"}]})
        self.dialogs.notify.assert_called_once_with("Retry", "files are gone")
        self.runs.queue.replace.assert_not_called()


class ListCancelClearTests(Setup):
    def test_listing_notes_the_run_the_dialog_follows(self):
        self.assertEqual(self.runs.list({"watching": "r7"}), {"jobs": [{"id": "r0"}]})
        self.assertTrue(self.runs._watched.following("r7"))
        self.runs.list({})   # a dialog that follows none

    def test_cancel_and_clear_go_to_the_queue_and_answer_the_list(self):
        self.assertEqual(self.runs.cancel({"id": "r1"}), {"jobs": [{"id": "r0"}]})
        self.runs.queue.cancel.assert_called_once_with("r1")
        self.runs.cancel({})
        self.runs.queue.cancel.assert_called_with("")
        self.assertEqual(self.runs.clear({}), {"jobs": [{"id": "r0"}]})
        self.runs.queue.clear_finished.assert_called_once()


class AnnounceTests(Setup, Reports):
    def setUp(self):
        Setup.setUp(self)
        Reports.setUp(self)

    def test_a_run_the_dialog_follows_gets_no_message_box(self):
        self.runs._watched.touch("r1")
        self.runs._announce(finished("publish", "error"))
        self.alerts.alert.assert_not_called()
        self.alerts.done.assert_not_called()

    def test_a_failed_run_gets_a_warning_and_a_good_one_a_note(self):
        self.runs._announce(finished("publish", "error", run_id="a"))
        self.alerts.alert.assert_called_once()
        self.assertEqual(self.alerts.alert.call_args[0][1], "Publish failed")
        self.runs._announce(finished("publish", "done", run_id="b"))
        self.alerts.done.assert_called_once()
        self.assertEqual(self.alerts.done.call_args[0][1], "Publish complete")

    def test_a_run_with_nothing_to_say_gets_no_message_box(self):
        self.runs._announce(finished("publish", "cancelled", run_id="c"))
        self.alerts.alert.assert_not_called()
        self.alerts.done.assert_not_called()


class RegisterTests(unittest.TestCase):
    def test_every_action_is_registered(self):
        bridge = MessageBridge()
        with mock.patch.object(publish_run_actions, "PublishRuns") as runs:
            register_publish_run_actions(bridge, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock())
        runs.return_value.cancel.return_value = {"jobs": []}
        self.assertEqual(bridge.dispatch("cancel_publish", '{"id": "r1"}')["result"], {"jobs": []})
        runs.return_value.cancel.assert_called_once_with({"id": "r1"})
        for action in ("start_publish", "retry_publish", "list_publish_jobs", "clear_publish_jobs"):
            self.assertNotEqual(bridge.dispatch(action, "{}")["error"], f"Unknown action: {action}", action)


if __name__ == "__main__":
    unittest.main()

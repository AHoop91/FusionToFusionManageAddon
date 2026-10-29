"""Validating workspace ids and listing the revision controlled workspaces. Run: python -m unittest discover tests"""

import threading
import unittest
from unittest import mock

from src.config.config_service import CompanyModeUnavailable
from src.config.workspace_models import ITEMS_KIND
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import workspace_actions
    from src.ui.actions.workspace_actions import WorkspaceChecks, register_workspace_actions
    from src.ui.message_bridge import MessageBridge


class ChecksTests(unittest.TestCase):
    def setUp(self):
        self.bridge = mock.Mock()
        self.queued = []   # the checks, run by the test when it wants them to finish
        self.make_client = mock.Mock(return_value=object())
        self.checks = WorkspaceChecks(self.bridge, self.make_client, self.queued.append)
        self.service = mock.Mock()
        self.service.return_value.validate.return_value = {"kind": ITEMS_KIND, "valid": True, "message": "Items"}
        patch = mock.patch.object(workspace_actions, "WorkspaceService", self.service)
        patch.start()
        self.addCleanup(patch.stop)

    def finish(self, which=None):
        """Run the check at index ``which`` of those waiting, or all of them."""
        if which is not None:
            self.queued.pop(which)()
            return
        while self.queued:
            self.queued.pop(0)()

    def test_a_check_is_pending_and_the_outcome_is_pushed_when_done(self):
        self.assertEqual(self.checks.start({"kind": ITEMS_KIND, "workspace_id": " 242 "}),
                         {"kind": ITEMS_KIND, "workspace_id": "242", "pending": True})
        self.assertTrue(self.checks.status({"kind": ITEMS_KIND})["pending"])
        self.finish()
        done = {"kind": ITEMS_KIND, "valid": True, "message": "Items", "workspace_id": "242", "pending": False}
        self.bridge.push.assert_called_once_with("validate_workspace_status", done)
        self.assertEqual(self.checks.status({"kind": ITEMS_KIND}), done)

    def test_the_id_is_checked_as_the_kind_that_was_asked_for(self):
        self.checks.start({"kind": ITEMS_KIND, "workspace_id": "242"})
        self.finish()
        kind, workspace_id = self.service.return_value.validate.call_args[0]
        self.assertEqual((kind.kind_id, workspace_id), (ITEMS_KIND, "242"))

    def test_a_kind_that_is_not_one_is_refused_and_nothing_is_checked(self):
        answer = self.checks.start({"kind": "nonsense", "workspace_id": "1"})
        self.assertEqual((answer["valid"], answer["pending"], answer["message"]), (False, False, "Unknown workspace type."))
        self.assertEqual(self.queued, [])

    def test_company_mode_being_unavailable_is_told_in_the_reply(self):
        self.make_client.side_effect = CompanyModeUnavailable("no company mode")
        answer = self.checks.start({"kind": ITEMS_KIND, "workspace_id": "1"})
        self.assertEqual((answer["valid"], answer["message"]), (False, "no company mode"))
        self.assertEqual(self.queued, [])
        self.assertEqual(self.checks.status({"kind": ITEMS_KIND})["message"], "No validation is running.")

    def test_a_failed_check_is_told_with_why(self):
        self.service.return_value.validate.side_effect = RuntimeError("down")
        self.checks.start({"kind": ITEMS_KIND, "workspace_id": "1"})
        self.finish()
        done = self.checks.status({"kind": ITEMS_KIND})
        self.assertEqual((done["valid"], done["pending"], done["message"]), (False, False, "Validation failed: down"))

    def test_a_failure_without_a_message_is_told_by_its_kind(self):
        self.service.return_value.validate.side_effect = RuntimeError()
        self.checks.start({"kind": ITEMS_KIND, "workspace_id": "1"})
        self.finish()
        self.assertEqual(self.checks.status({"kind": ITEMS_KIND})["message"], "Validation failed: RuntimeError")

    def test_a_kind_never_checked_says_no_validation_is_running(self):
        answer = self.checks.status({"kind": ITEMS_KIND})
        self.assertEqual((answer["valid"], answer["message"]), (False, "No validation is running."))

    def test_the_outcome_handed_back_is_a_copy(self):
        self.checks.start({"kind": ITEMS_KIND, "workspace_id": "1"})
        self.checks.status({"kind": ITEMS_KIND})["pending"] = False
        self.assertTrue(self.checks.status({"kind": ITEMS_KIND})["pending"])

    def test_the_check_of_an_id_since_changed_does_not_replace_the_newer_answer(self):
        self.service.return_value.validate.side_effect = lambda kind, workspace_id: {"valid": True, "message": f"id {workspace_id}"}
        self.checks.start({"kind": ITEMS_KIND, "workspace_id": "1"})
        self.checks.start({"kind": ITEMS_KIND, "workspace_id": "2"})
        self.finish(which=1)   # the newer one finishes first
        self.finish(which=0)   # and the older one, late
        self.assertEqual(self.bridge.push.call_count, 1)
        self.assertEqual(self.bridge.push.call_args[0][1]["workspace_id"], "2")
        self.assertEqual(self.checks.status({"kind": ITEMS_KIND})["message"], "id 2")

    def test_a_runner_that_does_the_check_at_once_does_not_deadlock(self):
        checks = WorkspaceChecks(self.bridge, self.make_client, lambda work: work())
        done = []
        thread = threading.Thread(target=lambda: done.append(checks.start({"kind": ITEMS_KIND, "workspace_id": "1"})), daemon=True)
        thread.start()
        thread.join(5)
        self.assertEqual(len(done), 1)
        self.assertFalse(checks.status({"kind": ITEMS_KIND})["pending"])


class RegisteredActionsTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MessageBridge()
        self.queued = []
        self.config = mock.Mock()
        self.service = mock.Mock()
        self.service.return_value.revision_controlled.return_value = [{"id": "242", "name": "Items"}]
        for patch in (mock.patch.object(workspace_actions, "FmClient"),
                      mock.patch.object(workspace_actions, "WorkspaceService", self.service)):
            patch.start()
            self.addCleanup(patch.stop)
        register_workspace_actions(self.bridge, self.config, mock.Mock(), self.queued.append)

    def call(self, action, payload=""):
        return self.bridge.dispatch(action, payload)

    def finish(self):
        while self.queued:
            self.queued.pop(0)()

    def test_the_workspaces_are_listed_in_the_background(self):
        result = self.call("list_workspaces")["result"]
        self.assertEqual((result["pending"], result["workspaces"]), (True, []))
        self.finish()
        done = self.call("list_workspaces_status")["result"]
        self.assertEqual((done["pending"], done["ok"], done["workspaces"]), (False, True, [{"id": "242", "name": "Items"}]))

    def test_a_failed_listing_is_told_with_why(self):
        self.service.return_value.revision_controlled.side_effect = RuntimeError("down")
        self.call("list_workspaces")
        self.finish()
        done = self.call("list_workspaces_status")["result"]
        self.assertEqual((done["ok"], done["message"], done["workspaces"]), (False, "down", []))

    def test_company_mode_being_unavailable_is_told_in_the_listing_reply(self):
        self.config.effective_settings.side_effect = CompanyModeUnavailable("no company mode")
        result = self.call("list_workspaces")["result"]
        self.assertEqual((result["ok"], result["message"], result["workspaces"]), (False, "no company mode", []))
        self.assertEqual(self.queued, [])

    def test_asking_for_the_list_again_while_it_is_read_starts_no_second_read(self):
        self.call("list_workspaces")
        self.call("list_workspaces")
        self.assertEqual(len(self.queued), 1)

    def test_validation_goes_through_the_bridge_with_the_kind_and_id(self):
        result = self.call("validate_workspace", f'{{"kind": "{ITEMS_KIND}", "workspace_id": "242"}}')["result"]
        self.assertEqual((result["kind"], result["workspace_id"], result["pending"]), (ITEMS_KIND, "242", True))
        self.assertTrue(self.call("validate_workspace_status", f'{{"kind": "{ITEMS_KIND}"}}')["result"]["pending"])


if __name__ == "__main__":
    unittest.main()

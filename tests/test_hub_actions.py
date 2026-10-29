"""The user's role in the active hub, as the palette asks for it. Run: python -m unittest discover tests"""

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from src.fusion_mfg.hub_role import NOT_ADMIN, UNKNOWN, HubRole
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import hub_actions
    from src.ui.actions.hub_actions import KEPT_SECONDS, RETRY_AFTER_SECONDS, HubRoles, register_hub_actions
    from src.ui.message_bridge import MessageBridge

ADMIN = HubRole(admin=True, known=True, role="ADMIN")
MEMBER = HubRole(admin=False, known=True, role="MEMBER")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class HubRolesTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(hub_id="hub-1", hub_name="Hub One")
        self.bridge = mock.Mock()
        self.clock = Clock()
        self.email = " Ada@Example.com "
        self.queued = []   # the reads, run by the test when it wants them to finish
        self.roles = HubRoles(self.bridge, self.config, lambda: self.email, run=self.queued.append, clock=self.clock)
        self.read_role = mock.Mock(return_value=ADMIN)
        self.read_id = mock.Mock(return_value="dm-1")
        for patch in (mock.patch.object(hub_actions, "FusionGraphQlClient"),
                      mock.patch.object(hub_actions, "read_hub_role", self.read_role),
                      mock.patch.object(hub_actions, "read_hub_id", self.read_id)):
            patch.start()
            self.addCleanup(patch.stop)

    def finish_reads(self):
        while self.queued:
            self.queued.pop(0)()

    def test_the_first_ask_is_pending_and_the_role_is_pushed_when_read(self):
        self.assertEqual(self.roles.get(), {"state": "pending", "role": ""})
        self.finish_reads()
        self.bridge.push.assert_called_once_with("get_hub_role", {"state": "admin", "role": "ADMIN"})

    def test_the_role_is_read_for_the_email_in_lower_case_and_the_hubs_data_model_id(self):
        self.roles.get()
        self.finish_reads()
        self.read_id.assert_called_once()
        self.assertEqual(self.read_id.call_args[0][1], "Hub One")
        self.assertEqual(self.read_role.call_args[0][1:], ("dm-1", "ada@example.com"))

    def test_a_member_is_told_from_an_admin(self):
        self.read_role.return_value = MEMBER
        self.roles.get()
        self.finish_reads()
        self.assertEqual(self.roles.get(), {"state": "member", "role": "MEMBER"})

    def test_a_clear_answer_is_kept_for_a_while_then_asked_for_again(self):
        self.roles.get()
        self.finish_reads()
        self.clock.now += KEPT_SECONDS - 1
        self.assertEqual(self.roles.get()["state"], "admin")
        self.assertEqual(self.queued, [])
        self.clock.now += 2
        self.assertEqual(self.roles.get()["state"], "pending")
        self.assertEqual(len(self.queued), 1)

    def test_a_refresh_asks_again_at_once(self):
        self.roles.get()
        self.finish_reads()
        self.assertEqual(self.roles.get(refresh=True)["state"], "pending")

    def test_a_runner_that_does_the_read_at_once_does_not_deadlock(self):
        roles = HubRoles(self.bridge, self.config, lambda: self.email, run=lambda work: work(), clock=self.clock)
        done = []
        thread = threading.Thread(target=lambda: done.append(roles.get()), daemon=True)
        thread.start()
        thread.join(5)
        self.assertEqual(done, [{"state": "pending", "role": ""}])
        self.assertEqual(roles.get()["state"], "admin")

    def test_asking_while_it_is_read_starts_no_second_read(self):
        self.roles.get()
        self.roles.get()
        self.assertEqual(len(self.queued), 1)

    def test_an_answer_that_could_not_be_had_is_unknown_for_a_while_then_asked_for_again(self):
        self.read_role.return_value = UNKNOWN
        self.roles.get()
        self.finish_reads()
        self.bridge.push.assert_called_once_with("get_hub_role", {"state": "unknown", "role": ""})
        self.assertEqual(self.roles.get()["state"], "unknown")
        self.assertEqual(self.queued, [])
        self.clock.now += RETRY_AFTER_SECONDS
        self.assertEqual(self.roles.get()["state"], "pending")

    def test_a_refusal_to_say_who_is_an_admin_is_a_clear_answer(self):
        self.read_role.return_value = NOT_ADMIN
        self.roles.get()
        self.finish_reads()
        self.assertEqual(self.roles.get()["state"], "member")

    def test_a_read_that_raises_is_unknown_and_the_panel_is_told(self):
        self.read_role.side_effect = RuntimeError("boom")
        self.roles.get()
        self.finish_reads()
        self.bridge.push.assert_called_once_with("get_hub_role", {"state": "unknown", "role": ""})
        self.assertEqual(self.roles.get()["state"], "unknown")

    def test_the_hubs_data_model_id_is_asked_for_once(self):
        self.roles.get()
        self.finish_reads()
        self.roles.get(refresh=True)
        self.finish_reads()
        self.read_id.assert_called_once()

    def test_an_empty_hub_id_is_asked_for_again(self):
        self.read_id.return_value = ""
        self.roles.get()
        self.finish_reads()
        self.roles.get(refresh=True)
        self.finish_reads()
        self.assertEqual(self.read_id.call_count, 2)

    def test_nothing_is_pushed_when_the_user_moved_to_another_hub_meanwhile(self):
        self.roles.get()
        self.config.hub_id = "hub-2"
        self.finish_reads()
        self.bridge.push.assert_not_called()

    def test_without_a_hub_or_a_user_the_role_is_unknown_and_not_read(self):
        self.config.hub_id = ""
        self.assertEqual(self.roles.get()["state"], "unknown")
        self.config.hub_id, self.email = "hub-1", "  "
        self.assertEqual(self.roles.get()["state"], "unknown")
        self.assertEqual(self.queued, [])


class RegisterTests(unittest.TestCase):
    def test_a_refresh_in_the_request_is_passed_on_and_the_role_is_read_at_start_up(self):
        bridge = MessageBridge()
        config = SimpleNamespace(hub_id="hub-1", hub_name="Hub One")
        with mock.patch.object(hub_actions, "HubRoles") as roles:
            register_hub_actions(bridge, config)
            roles.return_value.get.assert_called_once_with()   # the head start
            bridge.dispatch("get_hub_role", '{"refresh": true}')
            roles.return_value.get.assert_called_with(True)
            bridge.dispatch("get_hub_role", "")
            roles.return_value.get.assert_called_with(False)

    def test_a_head_start_that_fails_does_not_stop_the_add_in_loading(self):
        with mock.patch.object(hub_actions, "HubRoles") as roles:
            roles.return_value.get.side_effect = RuntimeError("no Fusion")
            register_hub_actions(mock.Mock(), SimpleNamespace())


if __name__ == "__main__":
    unittest.main()

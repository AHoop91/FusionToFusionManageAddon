"""The auth actions of the palette. Run: python -m unittest discover tests"""

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from src.config.config_service import CompanyModeUnavailable
from tests.hub_fixtures import auth_of
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import auth_actions
    from src.ui.actions.auth_actions import ProfileReads, register_auth_actions
    from src.ui.message_bridge import MessageBridge

USER = {"user_id": "u1", "name": "Ada", "email": "", "picture": "", "picture_large": "", "tenant": "t"}
EMPTY = {"user_id": "", "name": "", "email": "", "picture": "", "picture_large": "", "tenant": "t"}


def settings(tenant="t", client_id="c"):
    return SimpleNamespace(tenant=tenant, client_id=client_id)


class ProfileReadsTests(unittest.TestCase):
    def setUp(self):
        self.config = mock.Mock()
        self.config.effective_settings.return_value = settings()
        self.bridge = mock.Mock()
        self.queued = []   # the reads, run by the test when it wants them to finish
        self.auth = auth_of()
        self.reads = ProfileReads(self.bridge, self.config, self.auth, run=self.queued.append)
        self.service = mock.Mock()
        self.service.current.return_value = USER
        self.service.empty.return_value = EMPTY
        patches = (mock.patch.object(auth_actions, "FmClient"),
                   mock.patch.object(auth_actions, "ProfileService", return_value=self.service))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def finish_reads(self):
        while self.queued:
            self.queued.pop(0)()

    def test_the_first_ask_is_pending_and_the_profile_is_pushed_when_read(self):
        self.assertEqual(self.reads.get(), {"pending": True})
        self.finish_reads()
        self.bridge.push.assert_called_once_with("auth_profile", USER)

    def test_a_runner_that_does_the_read_at_once_does_not_deadlock(self):
        reads = ProfileReads(self.bridge, self.config, auth_of(), run=lambda work: work())
        done = []
        thread = threading.Thread(target=lambda: done.append(reads.get()), daemon=True)
        thread.start()
        thread.join(5)
        self.assertEqual(done, [{"pending": True}])
        self.assertEqual(reads.get(), USER)

    def test_a_profile_read_is_kept_for_the_next_ask(self):
        self.reads.get()
        self.finish_reads()
        self.assertEqual(self.reads.get(), USER)
        self.assertEqual(self.queued, [])

    def test_asking_again_while_it_is_read_does_not_start_a_second_read(self):
        self.reads.get()
        self.reads.get()
        self.assertEqual(len(self.queued), 1)

    def test_an_empty_answer_is_handed_over_once_and_not_kept(self):
        self.service.current.return_value = EMPTY
        self.reads.get()
        self.finish_reads()
        self.assertEqual(self.reads.get(), EMPTY)
        self.assertEqual(self.reads.get(), {"pending": True})   # asked again, so it is read again

    def test_a_read_that_raises_gives_the_empty_profile(self):
        self.service.current.side_effect = RuntimeError("boom")
        self.reads.get()
        self.finish_reads()
        self.bridge.push.assert_called_once_with("auth_profile", EMPTY)

    def test_nothing_is_pushed_when_the_sign_in_settings_changed_meanwhile(self):
        self.reads.get()
        self.config.effective_settings.return_value = settings(client_id="other")
        self.finish_reads()
        self.bridge.push.assert_not_called()

    def test_nothing_is_pushed_when_the_settings_can_no_longer_be_had(self):
        self.reads.get()
        self.config.effective_settings.side_effect = CompanyModeUnavailable("no company mode")
        self.finish_reads()
        self.bridge.push.assert_not_called()

    def test_a_profile_read_for_one_user_is_not_handed_to_the_next_to_sign_in(self):
        self.reads.get()
        self.finish_reads()
        self.auth.session.return_value = 2   # the session ended without the user choosing to sign out (a refresh was refused), and another signed in
        self.assertEqual(self.reads.get(), {"pending": True})
        self.finish_reads()
        self.assertEqual(self.bridge.push.call_count, 2)

    def test_nothing_is_pushed_when_another_user_signed_in_while_it_was_read(self):
        self.reads.get()
        self.auth.session.return_value = 2
        self.finish_reads()
        self.bridge.push.assert_not_called()

    def test_a_read_under_way_at_sign_out_is_not_kept_or_pushed(self):
        self.reads.get()
        self.reads.forget()
        self.finish_reads()
        self.bridge.push.assert_not_called()
        self.assertEqual(self.reads.get(), {"pending": True})   # the old user's profile was not kept

    def test_sign_out_drops_the_kept_profile(self):
        self.reads.get()
        self.finish_reads()
        self.reads.forget()
        self.assertEqual(self.reads.get(), {"pending": True})

    def test_sign_out_drops_a_read_not_yet_handed_over(self):
        self.service.current.return_value = EMPTY   # an empty answer is held for the next ask, not kept
        self.reads.get()
        self.finish_reads()
        self.reads.forget()
        self.assertEqual(self.reads.get(), {"pending": True})


class RegisteredActionsTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MessageBridge()
        self.config = mock.Mock()
        self.config.effective_settings.return_value = settings()
        self.auth = mock.Mock()
        register_auth_actions(self.bridge, self.config, self.auth)

    def call(self, action):
        return self.bridge.dispatch(action, "")

    def test_status_is_the_services_answer_for_the_settings(self):
        self.auth.status.return_value = {"state": "signed_in", "error": ""}
        self.assertEqual(self.call("auth_status")["result"], {"state": "signed_in", "error": ""})
        self.auth.status.assert_called_once_with(self.config.effective_settings.return_value)

    def test_status_says_why_company_mode_is_unavailable(self):
        self.config.effective_settings.side_effect = CompanyModeUnavailable("no company mode")
        self.assertEqual(self.call("auth_status")["result"], {"state": "error", "error": "no company mode"})

    def test_login_starts_the_sign_in_and_says_so(self):
        self.assertEqual(self.call("auth_login")["result"], {"state": "signing_in", "error": ""})
        self.auth.start_login.assert_called_once()

    def test_a_login_the_service_refuses_is_an_error_reply(self):
        self.auth.start_login.side_effect = RuntimeError("Sign-in already in progress.")
        reply = self.call("auth_login")
        self.assertEqual((reply["ok"], reply["error"]), (False, "Sign-in already in progress."))

    def test_cancel_stops_the_pending_sign_in(self):
        self.call("auth_cancel")
        self.auth.cancel_login.assert_called_once()

    def test_logout_signs_out_and_says_so(self):
        self.assertEqual(self.call("auth_logout")["result"], {"state": "signed_out", "error": ""})
        self.auth.sign_out.assert_called_once()

    def test_the_panel_is_told_how_a_browser_sign_in_ended(self):
        self.auth.status.return_value = {"state": "signed_in", "error": ""}
        pushed = []
        self.bridge.set_pusher(lambda action, text: pushed.append((action, text)))
        self.auth.set_on_login_done.call_args[0][0]()
        self.assertEqual([action for action, _ in pushed], ["auth_status"])


if __name__ == "__main__":
    unittest.main()

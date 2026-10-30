"""The Publish panel's actions: opening links and saying which design is open. Run: python -m unittest discover tests"""

import unittest
from unittest import mock

from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import publish_actions
    from src.ui.actions.publish_actions import is_openable, model_key, register_publish_actions
    from src.ui.message_bridge import MessageBridge


class IsOpenableTests(unittest.TestCase):
    def test_https_and_http_to_this_computer_are_openable(self):
        for url in ("https://example.com/a?b=1", "HTTPS://Example.com/", "http://localhost/AutodeskDM/x", "http://127.0.0.1/x"):
            self.assertTrue(is_openable(url), url)

    def test_anything_else_is_not(self):
        for url in ("", "http://example.com/", "javascript:alert(1)", "file:///C:/Windows/notepad.exe", "ftp://example.com/",
                    "//example.com/", "example.com", "http://localhost.evil.com/", "http://localhost@evil.com/", "C:\\Windows\\notepad.exe"):
            self.assertFalse(is_openable(url), url)

    def test_a_link_with_a_space_or_control_character_is_not(self):
        for url in ("https://example.com/a b", "https://example.com/\nx", "https://example.com/\x00", "https://example.com/\x7f",
                    "https://example.com/\u2028"):
            self.assertFalse(is_openable(url), repr(url))


class ModelKeyTests(unittest.TestCase):
    def test_the_key_names_the_model_and_the_version(self):
        self.assertEqual(model_key("m1", "2024-01-01"), "m1|2024-01-01")

    def test_no_saved_design_has_no_key(self):
        self.assertEqual(model_key("", ""), "")
        self.assertEqual(model_key("", "2024-01-01"), "")


class RegisteredActionsTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MessageBridge()
        self.browser = mock.Mock(return_value=True)
        self.ref = mock.Mock(return_value=("m1", "t1"))
        patch = mock.patch.object(publish_actions, "PublishSections")
        self.sections = patch.start().return_value
        self.addCleanup(patch.stop)
        self.config = mock.Mock(hub_id="hub1")
        register_publish_actions(self.bridge, self.config, mock.Mock(), self.ref, self.browser)

    def test_the_sections_are_given_the_open_design_reader(self):
        self.assertIs(publish_actions.PublishSections.call_args[0][2], self.ref)

    def test_the_section_actions_go_to_the_sections(self):
        self.sections.request.return_value = {"pending": True}
        self.sections.status.return_value = {"done": True}
        self.assertEqual(self.bridge.dispatch("load_publish_section", '{"name": "summary"}')["result"], {"pending": True})
        self.assertEqual(self.bridge.dispatch("load_publish_section_status", "{}")["result"], {"done": True})
        self.sections.request.assert_called_once_with({"name": "summary"})

    def test_the_model_key_is_that_of_the_open_design(self):
        self.assertEqual(self.bridge.dispatch("get_publish_model_key", "")["result"], {"key": "m1|t1", "hub": "hub1"})
        self.ref.return_value = ("", "")
        self.assertEqual(self.bridge.dispatch("get_publish_model_key", "")["result"], {"key": "", "hub": "hub1"})

    def test_a_link_that_may_be_opened_is_opened(self):
        reply = self.bridge.dispatch("open_url", '{"url": "https://example.com/x"}')
        self.assertEqual((reply["ok"], reply["result"]), (True, {}))
        self.browser.assert_called_once_with("https://example.com/x")

    def test_a_link_that_may_not_be_is_refused_and_not_opened(self):
        for payload in ('{"url": "file:///C:/x"}', '{"url": ""}', "{}"):
            reply = self.bridge.dispatch("open_url", payload)
            self.assertEqual((reply["ok"], reply["error"]), (False, "Only https links can be opened."))
        self.browser.assert_not_called()

    def test_a_browser_that_does_not_open_is_logged_without_the_links_query(self):
        self.browser.return_value = False
        with mock.patch.object(publish_actions, "log") as log:
            reply = self.bridge.dispatch("open_url", '{"url": "https://example.com/x?token=secret"}')
        self.assertTrue(reply["ok"])
        self.assertNotIn("secret", str(log.warning.call_args))
        self.assertIn("https://example.com/x", str(log.warning.call_args))


if __name__ == "__main__":
    unittest.main()

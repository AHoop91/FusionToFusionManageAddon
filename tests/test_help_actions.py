"""The Help button opens the documentation, in the language in use when it has one. Run: python -m unittest discover -s tests -t ."""

import unittest
from unittest import mock

from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui.actions import help_actions
    from src.ui.message_bridge import MessageBridge


class HelpUrlTests(unittest.TestCase):
    def test_a_language_without_translated_pages_opens_the_english_ones(self):
        self.assertEqual(help_actions.help_url("de"), help_actions.DOCS_URL)
        self.assertEqual(help_actions.help_url(""), help_actions.DOCS_URL)

    def test_a_language_with_translated_pages_opens_its_own_folder(self):
        with mock.patch.object(help_actions, "DOCS_LANGUAGES", frozenset({"de", "pt-BR"})):
            self.assertEqual(help_actions.help_url("DE"), help_actions.DOCS_URL + "de/")
            self.assertEqual(help_actions.help_url("pt-br"), help_actions.DOCS_URL + "pt-BR/")
            self.assertEqual(help_actions.help_url("ja"), help_actions.DOCS_URL)

    def test_the_action_opens_the_link_in_the_browser(self):
        opened = []
        bridge = MessageBridge()
        help_actions.register_help_actions(bridge, lambda url: opened.append(url) or True)
        self.assertTrue(bridge.dispatch("open_help", "{}")["ok"])
        self.assertEqual(opened, [help_actions.DOCS_URL])


if __name__ == "__main__":
    unittest.main()

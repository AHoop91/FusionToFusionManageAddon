"""Choosing the language, and making a language file, from the panel. Run: python -m unittest discover -s tests -t ."""

import json
import os
import tempfile
import unittest

from src.core import i18n
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui.actions.language_actions import (delete_language, edit_language, language_payload, new_language, open_language_folder,
                                                 register_language_actions, set_language)
    from src.ui.message_bridge import MessageBridge


class LanguageActionTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.shipped, self.user, self.settings = (os.path.join(root.name, name) for name in ("shipped", "user", "settings"))
        os.makedirs(self.shipped)
        os.makedirs(self.settings)
        for code, name, strings in (("en", "English", {"a": "Hello"}), ("de", "Deutsch", {"a": "Hallo"})):
            with open(os.path.join(self.shipped, code + ".json"), "w", encoding="utf-8") as handle:
                json.dump({"language": name, "strings": strings}, handle)
        i18n.set_language("en", self.shipped, self.user)
        self.addCleanup(i18n.set_language, "en", user="")

    def test_the_payload_has_the_strings_and_the_languages_to_choose_from(self):
        payload = language_payload(self.shipped, self.user)
        self.assertEqual(payload["code"], "en")
        self.assertEqual([language["code"] for language in payload["languages"]], ["en", "de"])
        self.assertEqual(payload["user_dir"], self.user)

    def test_the_payload_says_when_the_ribbon_needs_a_restart_to_follow(self):
        self.addCleanup(setattr, i18n, "_ribbon_code", None)
        i18n.mark_ribbon()   # the ribbon was built in English
        self.assertFalse(language_payload(self.shipped, self.user)["restart"])
        set_language({"code": "de"}, self.settings, self.shipped, self.user)
        self.assertTrue(language_payload(self.shipped, self.user)["restart"])

    def test_choosing_a_language_uses_it_and_keeps_it(self):
        payload = set_language({"code": "de"}, self.settings, self.shipped, self.user)
        self.assertEqual((payload["code"], payload["strings"]["a"]), ("de", "Hallo"))
        self.assertEqual(i18n.t("a"), "Hallo")
        with open(os.path.join(self.settings, "language.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"language": "de"})

    def test_a_language_that_is_not_there_is_refused_and_nothing_is_kept(self):
        with self.assertRaises(ValueError):
            set_language({"code": "../x"}, self.settings, self.shipped, self.user)
        self.assertEqual(os.listdir(self.settings), [])
        self.assertEqual(i18n.active_code(), "en")

    def test_a_new_language_file_is_made_in_the_user_folder_and_found(self):
        payload = new_language({"code": "fr", "name": "Français"}, self.shipped, self.user)
        self.assertTrue(os.path.isfile(payload["created"]))
        self.assertIn("FR", [language["code"] for language in payload["languages"]])

    def test_the_languages_folder_is_made_and_opened(self):
        opened = []
        open_language_folder(self.user, opened.append)
        self.assertEqual(opened, [self.user])
        self.assertTrue(os.path.isdir(self.user))

    def test_anyone_may_make_a_language_or_open_the_folder(self):
        bridge = MessageBridge()
        register_language_actions(bridge, None)
        answer = bridge.dispatch("new_language", '{"code": "", "name": ""}')
        self.assertIn("Language code", answer["error"])   # refused for what it is, not for who asked

    def own(self, code="fr", name="Francais"):
        return new_language({"code": code, "name": name}, self.shipped, self.user)["created"]

    def test_a_language_of_the_users_own_is_opened_in_the_editor_by_its_file(self):
        path = self.own()
        opened = []
        answer = edit_language({"code": "fr"}, self.shipped, self.user, opened.append)
        self.assertEqual((opened, answer), ([path], {"code": "FR", "name": "Francais"}))

    def test_a_shipped_language_or_a_path_cannot_be_edited_or_deleted(self):
        for code in ("de", "en", "../shipped/de", "", "xx"):
            with self.assertRaises(ValueError, msg=code):
                edit_language({"code": code}, self.shipped, self.user, lambda path: self.fail("opened " + path))
            with self.assertRaises(ValueError, msg=code):
                delete_language({"code": code}, self.settings, self.shipped, self.user)
        self.assertTrue(os.path.isfile(os.path.join(self.shipped, "de.json")))

    def test_deleting_removes_the_file_and_nothing_else(self):
        path = self.own()
        other = self.own("es", "Espanol")
        answer = delete_language({"code": "fr"}, self.settings, self.shipped, self.user)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(other))
        self.assertEqual([l["code"] for l in answer["languages"]], ["en", "de", "ES"])

    def test_deleting_the_language_in_use_goes_back_to_english_and_forgets_the_choice(self):
        self.own()
        set_language({"code": "fr"}, self.settings, self.shipped, self.user)
        self.assertEqual(i18n.active_code(), "FR")
        answer = delete_language({"code": "fr"}, self.settings, self.shipped, self.user)
        self.assertEqual((answer["code"], i18n.active_code()), ("en", "en"))
        with open(os.path.join(self.settings, "language.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"language": "en"})

    def test_deleting_another_language_leaves_the_one_in_use_alone(self):
        self.own()
        set_language({"code": "de"}, self.settings, self.shipped, self.user)
        delete_language({"code": "fr"}, self.settings, self.shipped, self.user)
        self.assertEqual(i18n.active_code(), "de")

    def test_the_actions_are_registered_and_a_change_is_pushed_to_the_panels(self):
        pushed = []
        bridge = MessageBridge()
        register_language_actions(bridge, lambda action, data: pushed.append(action))
        self.assertTrue(bridge.dispatch("get_language", "{}")["ok"])
        self.assertFalse(bridge.dispatch("set_language", '{"code": "zz"}')["ok"])
        self.assertEqual(pushed, [])

    def test_the_ribbon_is_made_again_only_when_the_restart_is_asked_for(self):
        asked = []
        bridge = MessageBridge()
        register_language_actions(bridge, lambda action, data: None, lambda: asked.append(True))
        self.assertFalse(bridge.dispatch("set_language", '{"code": "zz"}')["ok"])
        self.assertEqual(asked, [])
        self.assertTrue(bridge.dispatch("restart_addin", "{}")["ok"])
        self.assertEqual(asked, [True])

    def test_the_restart_says_so_when_the_add_in_cannot_do_it(self):
        bridge = MessageBridge()
        register_language_actions(bridge)
        self.assertFalse(bridge.dispatch("restart_addin", "{}")["ok"])


if __name__ == "__main__":
    unittest.main()

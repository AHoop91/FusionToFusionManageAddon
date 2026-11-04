"""The language files: finding them, loading a language over English, the user's own files. Run: python -m unittest discover -s tests -t ."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from src.config.language_setting import read_language, write_language
from src.core import i18n


def write(folder, code, data):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, code + ".json"), "w", encoding="utf-8") as handle:
        handle.write(data if isinstance(data, str) else json.dumps(data))


class LanguageFolders(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.shipped, self.user = os.path.join(root.name, "shipped"), os.path.join(root.name, "user")
        write(self.shipped, "en", {"language": "English", "strings": {"a": "Hello", "b": "Hi {name}", "c": "Only English"}})
        write(self.shipped, "de", {"language": "Deutsch", "strings": {"a": "Hallo", "b": "Hallo {name}"}})
        self.addCleanup(i18n.set_language, "en")


class AvailableTests(LanguageFolders):
    def test_english_comes_first_then_the_others_by_name(self):
        write(self.user, "fr", {"language": "Français", "strings": {}})
        codes = [language.code for language in i18n.available(self.shipped, self.user)]
        self.assertEqual(codes, ["en", "de", "fr"])

    def test_a_user_file_replaces_a_shipped_one_of_the_same_code(self):
        write(self.user, "de", {"language": "Deutsch (mine)", "strings": {}})
        german = i18n.find("de", self.shipped, self.user)
        self.assertEqual((german.name, german.source), ("Deutsch (mine)", i18n.SOURCE_USER))

    def test_files_that_are_not_languages_are_left_out(self):
        write(self.user, "notes", "{}")
        write(self.user, "xx", "not json")
        write(self.user, "..", "{}")
        open(os.path.join(self.user, "readme.txt"), "w").close()
        self.assertEqual([language.code for language in i18n.available(self.shipped, self.user)], ["en", "de"])

    def test_a_code_is_never_used_as_a_path(self):
        write(self.user, "es", {"language": "Español", "strings": {}})
        self.assertIsNone(i18n.find("../shipped/en", self.shipped, self.user))
        self.assertIsNone(i18n.find("", self.shipped, self.user))

    def test_a_missing_user_folder_is_no_languages(self):
        self.assertEqual([language.code for language in i18n.available(self.shipped, "")], ["en", "de"])


class LoadTests(LanguageFolders):
    def test_the_language_over_english(self):
        strings = i18n.load("de", self.shipped, self.user)
        self.assertEqual(strings, {"a": "Hallo", "b": "Hallo {name}", "c": "Only English"})

    def test_an_unknown_language_is_english(self):
        self.assertEqual(i18n.load("xx", self.shipped, self.user)["a"], "Hello")

    def test_text_with_other_placeholders_than_english_is_not_used(self):
        write(self.user, "es", {"language": "Español", "strings": {"b": "Hola {nombre}", "a": "Hola"}})
        strings = i18n.load("es", self.shipped, self.user)
        self.assertEqual((strings["a"], strings["b"]), ("Hola", "Hi {name}"))

    def test_entries_that_are_not_text_are_left_out(self):
        write(self.user, "es", {"language": "Español", "strings": {"a": 5, "c": "Solo"}})
        strings = i18n.load("es", self.shipped, self.user)
        self.assertEqual((strings["a"], strings["c"]), ("Hello", "Solo"))

    def test_a_file_that_cannot_be_read_is_english(self):
        write(self.user, "es", "{ broken")
        self.assertEqual(i18n.load("es", self.shipped, self.user)["a"], "Hello")


class UseTests(LanguageFolders):
    def test_t_answers_the_text_in_the_language_in_use_and_fills_it(self):
        self.assertEqual(i18n.set_language("de", self.shipped, self.user), "de")
        self.assertEqual(i18n.t("b", name="Ann"), "Hallo Ann")

    def test_a_key_nothing_has_is_answered_as_itself(self):
        i18n.set_language("de", self.shipped, self.user)
        self.assertEqual(i18n.t("nothing.here"), "nothing.here")

    def test_a_language_that_is_not_there_leaves_english_in_use(self):
        self.assertEqual(i18n.set_language("xx", self.shipped, self.user), "en")

    def test_a_placeholder_without_a_value_is_left_as_it_is(self):
        self.assertEqual(i18n.fill("Hi {name} {other}", {"name": "Ann"}), "Hi Ann {other}")


class CreateTests(LanguageFolders):
    def test_it_starts_from_english_in_the_user_folder(self):
        path = i18n.create("pt-BR", "Português", self.shipped, self.user)
        self.assertEqual(os.path.dirname(path), self.user)
        self.assertEqual(os.path.basename(path), "PT-BR.json", "a code is kept in capitals")
        self.assertEqual(i18n.create("fr", "français du test", self.shipped, self.user) and i18n.find("fr", self.shipped, self.user).name, "Français Du Test", "each word of a name starts with a capital")
        made = i18n.find("pt-BR", self.shipped, self.user)
        self.assertEqual((made.name, made.source), ("Português", i18n.SOURCE_USER))
        self.assertEqual(i18n.load("pt-BR", self.shipped, self.user)["a"], "Hello")

    def test_a_code_that_is_taken_or_is_not_a_code_is_refused(self):
        for code in ("de", "en", "../x", "d", ""):
            with self.assertRaises(ValueError, msg=code):
                i18n.create(code, "Name", self.shipped, self.user)

    def test_a_name_is_needed(self):
        with self.assertRaises(ValueError):
            i18n.create("fr", "  ", self.shipped, self.user)


class ShippedEnglishTests(unittest.TestCase):
    def test_the_add_in_ships_english(self):
        english = i18n.find("en", i18n.shipped_dir(), "")
        self.assertIsNotNone(english)
        self.assertEqual(english.source, i18n.SOURCE_SHIPPED)

    def test_the_language_in_use_starts_as_english(self):
        i18n.set_language("en", user="")
        self.assertEqual(i18n.active_code(), "en")


class RestartTests(LanguageFolders):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, i18n, "_ribbon_code", None)

    def test_a_restart_is_not_asked_for_before_the_ribbon_is_built_or_while_the_language_is_the_same(self):
        self.assertFalse(i18n.restart_needed())
        i18n.set_language("de", self.shipped, self.user)
        i18n.mark_ribbon()
        self.assertFalse(i18n.restart_needed())

    def test_a_language_other_than_the_one_the_ribbon_was_built_in_needs_a_restart(self):
        i18n.set_language("de", self.shipped, self.user)
        i18n.mark_ribbon()
        i18n.set_language("en", self.shipped, self.user)
        self.assertTrue(i18n.restart_needed())
        i18n.set_language("de", self.shipped, self.user)
        self.assertFalse(i18n.restart_needed(), "back to the one it was built in")


class StartUpTests(unittest.TestCase):
    def test_the_language_module_loads_first_when_the_logs_are_in_the_users_folder(self):
        """Fusion has no ``MFGTOFM_LOG_DIR``: the logger asks ``paths`` for the user's folder while ``i18n`` is still loading, so
        ``paths`` must not need ``i18n`` (a circular import kept the add-in from loading)."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {key: value for key, value in os.environ.items() if key != "MFGTOFM_LOG_DIR"}
        with tempfile.TemporaryDirectory() as folder:
            env.update(LOCALAPPDATA=folder, APPDATA=folder, HOME=folder)
            done = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import src.core.i18n", root],
                                  env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)


class SettingTests(unittest.TestCase):
    def test_the_choice_is_kept_and_read_again(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(read_language(folder), "en")
            write_language("de", folder)
            self.assertEqual(read_language(folder), "de")

    def test_a_file_that_cannot_be_read_is_english(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "language.json"), "w") as handle:
                handle.write("[1]")
            self.assertEqual(read_language(folder), "en")


if __name__ == "__main__":
    unittest.main()

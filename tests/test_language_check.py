"""Checking a language file against English's: its shape, and whether every text maps onto a name English has.
Run: python -m unittest discover -s tests -t ."""

import json
import os
import tempfile
import unittest

from src.core import i18n, language_check
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui.actions.language_actions import check_language, language_payload, set_language

ENGLISH = {"a": "Hello", "b": "Hi {name}", "c": "{n} items of {total}", "d": "Plain"}


def write(folder, name, data):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(data if isinstance(data, str) else json.dumps(data))
    return path


class Folders(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.shipped, self.user, self.settings = (os.path.join(root.name, n) for n in ("shipped", "user", "settings"))
        write(self.shipped, "en.json", {"language": "English", "strings": ENGLISH})
        self.addCleanup(i18n.set_hub_dir, None)
        self.addCleanup(i18n.set_language, "en", user="", hub="")

    def file(self, data, name="de.json"):
        return write(self.user, name, data)


class CheckFileTests(Folders):
    def report(self, data):
        return language_check.check_file(self.file(data), ENGLISH)

    def test_a_full_translation_has_nothing_to_look_at(self):
        r = self.report({"language": "Deutsch", "strings": {"a": "Hallo", "b": "Hallo {name}", "c": "{n} von {total}", "d": "Einfach"}})
        self.assertEqual((r["errors"], r["warnings"], r["translated"], r["same_as_english"], r["missing_count"]), ([], [], 4, 0, 0))

    def test_texts_still_the_same_as_english_are_counted(self):
        r = self.report({"language": "Deutsch", "strings": {"a": "Hello", "b": "Hi {name}", "c": "{n} von {total}", "d": "Einfach"}})
        self.assertEqual((r["translated"], r["same_as_english"]), (4, 2))

    def test_names_english_has_and_the_file_lacks_are_missing(self):
        r = self.report({"language": "Deutsch", "strings": {"a": "Hallo"}})
        self.assertEqual((r["missing_count"], r["missing"], r["translated"]), (3, ["b", "c", "d"], 1))

    def test_text_with_other_placeholders_is_listed_with_both_sets_and_not_counted_as_translated(self):
        r = self.report({"language": "Deutsch", "strings": {"a": "Hallo", "b": "Hallo {nom}", "c": "{n} von"}})
        self.assertEqual(r["placeholder_count"], 2)
        self.assertEqual(r["placeholders"][0], {"key": "b", "expected": ["name"], "found": ["nom"]})
        self.assertEqual(r["placeholders"][1], {"key": "c", "expected": ["n", "total"], "found": ["n"]})
        self.assertEqual(r["translated"], 1)

    def test_entries_that_are_not_text_and_names_english_does_not_have_are_listed(self):
        r = self.report({"language": "Deutsch", "strings": {"a": "Hallo", "b": 5, "zzz": "Extra"}})
        self.assertEqual((r["not_text"], r["unknown"]), (["b"], ["zzz"]))

    def test_a_file_that_is_not_json_is_an_error_with_the_reason(self):
        r = self.report("{ broken")
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("not valid JSON", r["errors"][0])

    def test_a_file_of_the_wrong_shape_is_an_error(self):
        self.assertIn("must be a JSON object", self.report([1, 2])["errors"][0])
        self.assertIn("no \"strings\"", self.report({"language": "Deutsch"})["errors"][0])
        self.assertIn("none of the texts match".lower(), self.report({"language": "Deutsch", "strings": {"zzz": "x"}})["errors"][0].lower())

    def test_a_missing_name_is_a_warning_not_an_error(self):
        r = self.report({"strings": {"a": "Hallo"}})
        self.assertEqual((r["errors"], len(r["warnings"])), ([], 1))

    def test_a_long_list_is_cut_but_counted(self):
        english = {f"k{i}": "x" for i in range(100)}
        r = language_check.check_file(self.file({"language": "L", "strings": {"k0": "y"}}), english)
        self.assertEqual((r["missing_count"], len(r["missing"])), (99, language_check.LISTED))


class InvalidFilesTests(Folders):
    def test_files_that_cannot_be_used_are_named_with_the_reason(self):
        self.file({"language": "Deutsch", "strings": {"a": "Hallo"}})
        self.file("{ broken", "fr.json")
        self.file({"language": "Español"}, "es.json")
        self.file({"language": "Português", "strings": {"a": "Olá"}}, "pt_BR.json")
        write(self.user, "notes.txt", "x")
        found = {item["file"]: item["reason"] for item in language_check.invalid_files(self.user, "")}
        self.assertEqual(sorted(found), ["es.json", "fr.json", "pt_BR.json"])
        self.assertIn("language code", found["pt_BR.json"])

    def test_the_hubs_files_are_checked_too_and_say_where_they_are_from(self):
        hub = os.path.join(self.settings, "hub")
        write(hub, "fr.json", "{ broken")
        found = language_check.invalid_files("", hub)
        self.assertEqual([(i["file"], i["source"]) for i in found], [("fr.json", "hub")])


class ActionTests(Folders):
    def test_the_check_names_the_language_and_where_it_is_from(self):
        self.file({"language": "Deutsch", "strings": {"a": "Hallo"}})
        r = check_language({"code": "de"}, self.shipped, self.user)
        self.assertEqual((r["code"], r["name"], r["source"], r["translated"]), ("de", "Deutsch", "user", 1))

    def test_a_language_that_is_not_there_cannot_be_checked(self):
        with self.assertRaises(ValueError):
            check_language({"code": "xx"}, self.shipped, self.user)

    def test_a_language_whose_file_cannot_be_used_cannot_be_chosen(self):
        self.file({"language": "Deutsch", "strings": {"zzz": "nothing English has"}})
        with self.assertRaises(ValueError) as caught:
            set_language({"code": "de"}, self.settings, self.shipped, self.user)
        self.assertIn("cannot be used", str(caught.exception))
        self.assertEqual(i18n.active_code(), "en")
        self.assertFalse(os.path.exists(os.path.join(self.settings, "language.json")))

    def test_a_language_with_only_small_problems_can_be_chosen(self):
        self.file({"language": "Deutsch", "strings": {"a": "Hallo", "b": "Hallo {nom}"}})
        self.assertEqual(set_language({"code": "de"}, self.settings, self.shipped, self.user)["code"], "de")

    def test_the_payload_names_the_files_that_cannot_be_used(self):
        self.file("{ broken", "fr.json")
        self.assertEqual([i["file"] for i in language_payload(self.shipped, self.user)["invalid"]], ["fr.json"])


if __name__ == "__main__":
    unittest.main()

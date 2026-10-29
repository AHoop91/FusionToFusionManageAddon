"""The folder of a publish run: its names, what it records, and the files it writes."""

import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock

from src.publish import writer
from src.publish.writer import FAILED, NAME_CHARS, OK, SKIPPED, PublishFolder, safe_name


class SafeNameTests(unittest.TestCase):
    def test_path_characters_are_replaced_and_runs_of_them_are_one_underscore(self):
        self.assertEqual(safe_name('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(safe_name("a//\\\\b"), "a_b")
        self.assertEqual(safe_name("tab\there"), "tab_here")

    def test_a_name_does_not_end_in_a_dot_or_a_space(self):
        self.assertEqual(safe_name("  PN-1. . "), "PN-1")

    def test_a_name_that_is_empty_or_all_dots_takes_the_fallback(self):
        self.assertEqual(safe_name(""), "item")
        self.assertEqual(safe_name(None), "item")
        self.assertEqual(safe_name(" ... "), "item")
        self.assertEqual(safe_name("", "design"), "design")

    def test_a_long_name_is_cut_and_the_cut_does_not_leave_a_trailing_space_or_dot(self):
        self.assertEqual(safe_name("x" * 200), "x" * NAME_CHARS)
        self.assertEqual(safe_name("x" * (NAME_CHARS - 1) + " tail"), "x" * (NAME_CHARS - 1))
        self.assertEqual(safe_name("x" * (NAME_CHARS - 1) + ".tail"), "x" * (NAME_CHARS - 1))

    def test_a_name_the_system_keeps_for_a_device_is_prefixed(self):
        for name in ("CON", "con", "NUL", "aux", "PRN", "COM1", "com9", "LPT1", "con.step", "NUL.txt", "AUX."):
            with self.subTest(name=name):
                self.assertTrue(safe_name(name).startswith("_"), safe_name(name))

    def test_names_that_only_look_like_a_device_are_left_alone(self):
        for name in ("CONSOLE", "COM10", "COM0", "LPT", "my.con", "PN-CON"):
            with self.subTest(name=name):
                self.assertEqual(safe_name(name), name)

    def test_letters_of_other_alphabets_are_kept(self):
        self.assertEqual(safe_name("Zahnräder-Ø12"), "Zahnräder-Ø12")


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.parent = self.dir.name

    def test_a_run_has_a_folder_of_its_own_named_by_its_design_and_the_time(self):
        with mock.patch.object(writer, "datetime") as clock:
            clock.now.return_value = datetime(2026, 3, 4, 5, 6, 7)
            folder = PublishFolder(self.parent, "PN/1")
        self.assertEqual(folder.path, os.path.join(self.parent, "PN_1_20260304-050607"))
        self.assertTrue(os.path.isdir(folder.path))

    def test_runs_of_one_design_started_in_the_same_second_each_get_a_folder(self):
        with mock.patch.object(writer, "datetime") as clock:
            clock.now.return_value = datetime(2026, 3, 4, 5, 6, 7)
            paths = [PublishFolder(self.parent, "PN-1").path for _ in range(3)]
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual([os.path.basename(p) for p in paths], ["PN-1_20260304-050607", "PN-1_20260304-050607_2", "PN-1_20260304-050607_3"])
        self.assertTrue(all(os.path.isdir(p) for p in paths))

    def test_a_design_with_no_number_is_called_design(self):
        self.assertTrue(os.path.basename(PublishFolder(self.parent, "").path).startswith("design_"))

    def test_the_folders_of_items_are_one_each_even_when_numbers_make_the_same_name(self):
        folder = PublishFolder(self.parent, "R")
        dirs = [folder.item_dir(number) for number in ("A/B", "A:B", "a/b")]
        self.assertEqual(dirs, [os.path.join("items", "A_B"), os.path.join("items", "A_B_2"), os.path.join("items", "a_b_3")])

    def test_an_item_numbered_like_the_name_given_to_another_gets_a_folder_of_its_own(self):
        folder = PublishFolder(self.parent, "R")
        dirs = [folder.item_dir(number) for number in ("X", "X", "X_2")]
        self.assertEqual(len({d.lower() for d in dirs}), 3)
        self.assertEqual(dirs[:2], [os.path.join("items", "X"), os.path.join("items", "X_2")])

    def test_threads_asking_for_the_same_item_are_each_given_a_folder_of_their_own(self):
        folder, given = PublishFolder(self.parent, "R"), []

        def ask():
            given.extend(folder.item_dir("PN-1") for _ in range(50))

        threads = [threading.Thread(target=ask) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(given), 400)
        self.assertEqual(len(set(given)), 400)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = PublishFolder(self.dir.name, "R")

    def test_json_is_written_whole_with_the_folders_to_it_and_letters_as_they_are(self):
        path = self.folder.write_json(os.path.join("items", "A", "item.request.json"), {"name": "Ø12", "n": [1, 2]})
        self.assertEqual(path, os.path.join(self.folder.path, "items", "A", "item.request.json"))
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("Ø12", text)   # not \\u00d812
        self.assertEqual(json.loads(text), {"name": "Ø12", "n": [1, 2]})

    def test_bytes_are_written_whole(self):
        path = self.folder.write_bytes("thumbnail.png", b"\x89PNG")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"\x89PNG")

    def test_a_file_written_again_is_the_new_one_whole_and_nothing_is_left_beside_it(self):
        self.folder.write_json("a.json", {"first": "x" * 1000})
        self.folder.write_json("a.json", {"second": 1})
        with open(os.path.join(self.folder.path, "a.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"second": 1})
        self.assertEqual(os.listdir(self.folder.path), ["a.json"])


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = PublishFolder(self.dir.name, "R")

    def test_what_is_recorded_of_an_item_is_asked_for_by_the_item(self):
        self.folder.record("A", "thumbnail", OK, "10 bytes", "t.png")
        self.folder.record("B", "item request", FAILED, "no")
        self.folder.record("A", "item request", SKIPPED, "same")
        self.assertEqual([e["artifact"] for e in self.folder.entries_of("A")], ["thumbnail", "item request"])
        self.assertEqual(self.folder.entries_of("A")[0], {"item": "A", "artifact": "thumbnail", "status": OK, "detail": "10 bytes", "file": "t.png"})
        self.assertEqual(self.folder.entries_of("nobody"), [])

    def test_the_entries_are_counted_by_status(self):
        for status in (OK, OK, FAILED, SKIPPED, OK):
            self.folder.record("A", "x", status)
        self.assertEqual(self.folder.counts(), {OK: 3, FAILED: 1, SKIPPED: 1})
        self.assertEqual(PublishFolder(self.dir.name, "Other").counts(), {})

    def test_recording_from_several_threads_loses_nothing(self):
        def record(name):
            for number in range(200):
                self.folder.record(name, "x", OK)

        threads = [threading.Thread(target=record, args=(name,)) for name in "abcd"]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.folder.counts(), {OK: 800})

    def test_the_manifest_holds_the_run_the_items_and_every_entry(self):
        self.folder.record("A", "item request", OK, "POST /x", "r.json")
        self.folder.set_item("A", {"id": "7", "state": "found", "request": "r.json"})
        self.folder.save_manifest({"root": "R", "workspace_id": "57", "message": "ok"})
        with open(os.path.join(self.folder.path, "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual((manifest["root"], manifest["workspace_id"], manifest["message"]), ("R", "57", "ok"))
        self.assertEqual(manifest["items"], {"A": {"id": "7", "state": "found", "request": "r.json"}})
        self.assertEqual(manifest["counts"], {OK: 1})
        self.assertEqual(manifest["artifacts"][0]["detail"], "POST /x")
        self.assertTrue(manifest["draft"])

    def test_the_manifest_is_whole_when_saved_again_and_has_nothing_beside_it(self):
        self.folder.save_manifest({"message": "first"})
        self.folder.record("A", "x", FAILED)
        self.folder.save_manifest({"message": "second"})
        with open(os.path.join(self.folder.path, "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual((manifest["message"], manifest["counts"]), ("second", {FAILED: 1}))
        self.assertEqual(os.listdir(self.folder.path), ["manifest.json"])


if __name__ == "__main__":
    unittest.main()

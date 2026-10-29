"""The folder the publish runs write into, and the removal that never leaves it. Run: python -m unittest discover tests"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src.publish import run_files
from src.publish.run_files import FOLDER_NAME, remove_run, temp_root


class RunFilesTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, "root")
        os.makedirs(self.root)

    def run_folder(self, name="PN-1_20260101-000000"):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.join(path, "items", "PN-2"))
        return path

    def test_the_root_is_one_folder_in_the_temporary_folder(self):
        self.assertEqual(os.path.dirname(temp_root()), tempfile.gettempdir())
        self.assertEqual(os.path.basename(temp_root()), FOLDER_NAME)

    def test_a_run_folder_is_removed_with_what_is_in_it(self):
        path = self.run_folder()
        self.assertTrue(remove_run(self.root, path))
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.isdir(self.root))

    def test_the_root_itself_is_not_removed(self):
        self.assertFalse(remove_run(self.root, self.root))
        self.assertTrue(os.path.isdir(self.root))

    def test_a_folder_outside_the_root_is_not_removed(self):
        other = os.path.join(self.base, "other")
        os.makedirs(other)
        self.assertFalse(remove_run(self.root, other))
        self.assertTrue(os.path.isdir(other))

    def test_a_folder_deeper_than_a_run_is_not_removed(self):
        deep = os.path.join(self.run_folder(), "items")
        self.assertFalse(remove_run(self.root, deep))
        self.assertTrue(os.path.isdir(deep))

    def test_dots_cannot_lead_out_of_the_root(self):
        other = os.path.join(self.base, "other")
        os.makedirs(other)
        self.assertFalse(remove_run(self.root, os.path.join(self.root, "..", "other")))
        self.assertTrue(os.path.isdir(other))

    def test_a_drive_or_filesystem_root_is_never_taken_for_a_run_folder(self):
        top = os.path.abspath(os.sep)
        self.assertFalse(run_files._inside(top, top))

    def test_a_root_written_in_another_letter_case_is_the_same_folder_where_the_filesystem_ignores_case(self):
        if not os.path.exists(self.root.swapcase()):
            self.skipTest("this filesystem tells names apart by letter case")
        path = self.run_folder()
        self.assertTrue(remove_run(self.root.swapcase(), path))

    def test_a_root_that_is_not_there_removes_nothing(self):
        path = self.run_folder()
        self.assertFalse(remove_run(os.path.join(self.base, "no-root"), path))
        self.assertTrue(os.path.isdir(path))

    def test_a_folder_that_is_not_there_is_not_removed_and_not_an_error(self):
        gone = os.path.join(self.root, "gone")
        self.assertFalse(remove_run(self.root, gone))
        self.assertFalse(remove_run(self.root, ""))

    def test_a_folder_removed_twice_is_removed_once(self):
        path = self.run_folder()
        self.assertTrue(remove_run(self.root, path))
        self.assertFalse(remove_run(self.root, path))

    def link_to(self, target, link):
        """Make ``link`` a link to the folder ``target``: a symbolic link, or on Windows (where that needs a privilege) a junction."""
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt" or subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True).returncode != 0:
                self.skipTest("this system does not let a link be made here")

    def test_a_link_to_a_folder_is_not_followed(self):
        target = os.path.join(self.base, "target")
        os.makedirs(os.path.join(target, "keep"))
        link = os.path.join(self.root, "link")
        self.link_to(target, link)
        self.assertFalse(remove_run(self.root, link))
        self.assertTrue(os.path.isdir(os.path.join(target, "keep")))

    def test_a_folder_that_cannot_be_removed_stays_and_is_said(self):
        path = self.run_folder()
        with mock.patch.object(run_files.shutil, "rmtree"), self.assertLogs(run_files.log, "WARNING") as logged:
            self.assertFalse(remove_run(self.root, path))
        self.assertIn("Could not remove all of", logged.output[0])
        self.assertTrue(os.path.isdir(path))

    def test_a_failure_while_removing_never_raises(self):
        path = self.run_folder()
        with mock.patch.object(run_files.shutil, "rmtree", side_effect=RuntimeError("boom")):
            self.assertFalse(remove_run(self.root, path))

    def test_no_root_removes_nothing(self):
        path = self.run_folder()
        self.assertFalse(remove_run(None, path))
        self.assertTrue(os.path.isdir(path))


if __name__ == "__main__":
    unittest.main()

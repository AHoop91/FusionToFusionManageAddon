"""The folder the publish runs write into, and the removal that never leaves it. Run: python -m unittest discover tests"""

import os
import shutil
import tempfile
import unittest

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

    def test_no_root_removes_nothing(self):
        path = self.run_folder()
        self.assertFalse(remove_run(None, path))
        self.assertTrue(os.path.isdir(path))


if __name__ == "__main__":
    unittest.main()

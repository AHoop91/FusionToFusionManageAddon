"""Writing a file whole or not at all."""

import os
import tempfile
import unittest
from unittest import mock

from src.core.atomic import REPLACE_TRIES, REPLACE_WAIT, replace_file, write_atomically


class AtomicTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "file.json")

    def read(self):
        with open(self.path, "rb") as handle:
            return handle.read()

    def test_the_data_is_the_whole_of_the_file_and_nothing_is_left_beside_it(self):
        write_atomically(self.path, b"first")
        write_atomically(self.path, b"2nd")
        self.assertEqual(self.read(), b"2nd")
        self.assertEqual(os.listdir(self.dir.name), ["file.json"])

    def test_a_file_that_cannot_be_put_in_place_leaves_the_old_one_as_it_was(self):
        write_atomically(self.path, b"old")
        with mock.patch("src.core.atomic.os.replace", side_effect=PermissionError("in use")), mock.patch("src.core.atomic.time.sleep"):
            with self.assertRaises(PermissionError):
                write_atomically(self.path, b"new")
        self.assertEqual(self.read(), b"old")

    def test_a_folder_that_is_not_there_is_an_error_not_a_created_folder(self):
        with self.assertRaises(OSError):
            write_atomically(os.path.join(self.dir.name, "missing", "file.json"), b"x")

    def test_a_refusal_for_a_moment_is_tried_again_with_a_longer_wait_each_time(self):
        real, refusals = os.replace, [PermissionError("in use"), PermissionError("in use")]

        def replace(source, target):
            if refusals:
                raise refusals.pop()
            real(source, target)

        with mock.patch("src.core.atomic.os.replace", replace), mock.patch("src.core.atomic.time.sleep") as sleep:
            write_atomically(self.path, b"data")
        self.assertEqual(self.read(), b"data")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [REPLACE_WAIT, REPLACE_WAIT * 2])

    def test_it_gives_up_after_the_tries_there_are(self):
        with mock.patch("src.core.atomic.os.replace", side_effect=PermissionError("in use")) as replace, mock.patch("src.core.atomic.time.sleep"):
            with self.assertRaises(PermissionError):
                replace_file("a", "b")
        self.assertEqual(replace.call_count, REPLACE_TRIES)

    def test_a_failure_that_is_not_a_refusal_is_not_tried_again(self):
        with mock.patch("src.core.atomic.os.replace", side_effect=FileNotFoundError("gone")) as replace:
            with self.assertRaises(FileNotFoundError):
                replace_file("a", "b")
        self.assertEqual(replace.call_count, 1)


if __name__ == "__main__":
    unittest.main()

"""Reading the hub through Fusion: work posted to Fusion's main thread, the plain wording of its errors, and what a listing looks like."""

import threading
import unittest
from unittest import mock

from src.fusion_mfg import fusion_hub_files
from src.fusion_mfg.fusion_hub_files import HubFilesError, _plain, by_name, run_on_main


def main_thread(task):
    """A stand-in for Fusion's main thread: runs the task on another thread, as the add-in's queue does."""
    threading.Thread(target=task).start()


class RunOnMainTests(unittest.TestCase):
    def test_the_result_of_the_work_is_handed_back(self):
        self.assertEqual(run_on_main(main_thread, lambda: 42), 42)

    def test_an_error_in_the_work_is_raised_to_the_caller(self):
        def work():
            raise ValueError("no")
        with self.assertRaises(ValueError):
            run_on_main(main_thread, work)

    def test_work_that_never_runs_ends_in_an_error_the_user_can_read(self):
        with mock.patch.object(fusion_hub_files, "MAIN_THREAD_WAIT_SECONDS", 0.05):
            with self.assertRaises(HubFilesError):
                run_on_main(lambda task: None, lambda: 1)


class PlainWordingTests(unittest.TestCase):
    def test_a_refused_download_says_who_can_download(self):
        error = '3 : Failed to download: 403 - {"errorCode":"AUTH-012"}'
        self.assertIn("viewers cannot download", _plain(error))

    def test_what_is_not_found_is_no_longer_in_the_hub(self):
        self.assertEqual(_plain("404 not found"), "That is no longer in the hub.")

    def test_an_error_nobody_expected_is_not_shown_raw(self):
        self.assertNotIn("0xDEAD", _plain("0xDEAD in module"))


class ListingTests(unittest.TestCase):
    def test_entries_are_sorted_by_name_ignoring_case(self):
        names = [e["name"] for e in by_name([{"id": "1", "name": "b"}, {"id": "2", "name": "A"}, {"id": "3", "name": "c"}])]
        self.assertEqual(names, ["A", "b", "c"])


if __name__ == "__main__":
    unittest.main()

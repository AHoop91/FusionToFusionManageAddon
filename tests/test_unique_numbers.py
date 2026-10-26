"""A publish run stops before it writes anything when a number is carried by several Fusion Manage items."""

import unittest
from unittest import mock

from src.publish.runner import PublishRun, SharedItemNumbers


def run_with_hits(hits_by_number):
    """A run that has only what ``_require_unique_numbers`` uses: the hits the shared search found per item number."""
    run = PublishRun.__new__(PublishRun)
    run._ahead = mock.Mock()
    run._ahead.found.side_effect = lambda number: hits_by_number.get(number)
    return run


def items(*numbers):
    return [{"item_number": number} for number in numbers]


class RequireUniqueNumbersTests(unittest.TestCase):
    def test_numbers_with_one_item_or_none_pass(self):
        run = run_with_hits({"PN-1": [{"id": "1"}], "PN-2": []})
        run._require_unique_numbers(items("PN-1", "PN-2", "PN-3"))   # PN-3: the search did not answer for it

    def test_a_number_with_several_items_stops_the_run_and_is_named(self):
        run = run_with_hits({"PN-1": [{"id": "1"}], "PN-6": [{"id": "6"}, {"id": "7"}], "PN-8": [{"id": "8"}, {"id": "9"}]})
        with self.assertRaises(SharedItemNumbers) as stopped:
            run._require_unique_numbers(items("PN-1", "PN-6", "PN-8"))
        self.assertEqual(stopped.exception.counts, {"PN-6": 2, "PN-8": 2})
        self.assertIn("Nothing was published", str(stopped.exception))

    def test_a_search_that_failed_stops_the_run(self):
        run = run_with_hits({})
        run._ahead.found.side_effect = RuntimeError("503")
        with self.assertRaises(RuntimeError):
            run._require_unique_numbers(items("PN-1"))


if __name__ == "__main__":
    unittest.main()

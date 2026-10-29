import unittest

from src.fm.change_log import parse_change_log
from src.fm.client import FmApiError

ENTRY = {
    "description": "New image uploaded", "action": {"shortName": "Edit Item"}, "user": {"title": "Pat"},
    "timeStamp": "2026-10-19T10:43:39.458-04:00",
    "details": [{"fieldName": "Image", "oldValue": "357", "newValue": "365"}],
}


class ChangeLogTests(unittest.TestCase):
    def test_row_from_an_entry(self):
        page = parse_change_log({"totalCount": 1, "items": [ENTRY]}, 0)
        self.assertEqual(page["rows"], [{"date": "2026-10-19T10:43:39.458-04:00", "user": "Pat", "action": "Edit Item", "description": "New image uploaded",
                                         "changes": [{"field": "Image", "old": "357", "new": "365"}]}])
        self.assertIsNone(page["next"])

    def test_a_missing_description_and_user_are_empty(self):
        (row,) = parse_change_log({"totalCount": 1, "items": [{"description": None, "action": {}, "details": []}]}, 0)["rows"]
        self.assertEqual((row["description"], row["user"], row["changes"]), ("", "", []))

    def test_the_next_page_starts_after_this_one(self):
        page = parse_change_log({"totalCount": 187, "items": [ENTRY] * 100}, 0)
        self.assertEqual(page["next"], 100)
        self.assertIsNone(parse_change_log({"totalCount": 187, "items": [ENTRY] * 87}, 100)["next"])

    def test_a_change_to_or_from_zero_is_kept(self):
        entry = {"details": [{"fieldName": "Qty", "oldValue": 0, "newValue": False}]}
        (row,) = parse_change_log({"totalCount": 1, "items": [entry]}, 0)["rows"]
        self.assertEqual(row["changes"], [{"field": "Qty", "old": "0", "new": "False"}])

    def test_a_total_that_is_not_a_number_ends_the_paging(self):
        page = parse_change_log({"totalCount": "many", "items": [ENTRY]}, 0)
        self.assertEqual((page["total"], page["next"]), (0, None))

    def test_nothing_logged(self):
        self.assertEqual(parse_change_log(None, 0), {"rows": [], "total": 0, "next": None})

    def test_unexpected_answer_is_an_error(self):
        with self.assertRaises(FmApiError):
            parse_change_log({"unexpected": 1}, 0)


if __name__ == "__main__":
    unittest.main()

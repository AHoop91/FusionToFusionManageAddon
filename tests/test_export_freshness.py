import unittest
from datetime import datetime, timezone

from src.ui.export_freshness import CURRENT, STALE, UNKNOWN, UNSAVED, compare, parse_stamp


def _epoch(*when):
    return datetime(*when, tzinfo=timezone.utc).timestamp()


class ParseStampTests(unittest.TestCase):
    def test_the_forms_fusion_manage_writes(self):
        expected = datetime(2026, 10, 13, 10, 15, 30, tzinfo=timezone.utc)
        for text in ("2026-10-13T10:15:30Z", "2026-10-13T10:15:30.000+0000", "2026-10-13T10:15:30+00:00", "2026-10-13T10:15:30"):
            self.assertEqual(parse_stamp(text), expected, text)

    def test_the_same_instant_in_another_zone_is_equal(self):
        self.assertEqual(parse_stamp("2026-10-13T12:15:30+02:00"), parse_stamp("2026-10-13T10:15:30Z"))

    def test_nothing_to_read(self):
        self.assertIsNone(parse_stamp(""))
        self.assertIsNone(parse_stamp(None))
        self.assertIsNone(parse_stamp("yesterday"))


class CompareTests(unittest.TestCase):
    SAVED = {"saved": _epoch(2026, 10, 13, 10, 0, 0), "unsaved": False, "reason": ""}

    def test_a_file_uploaded_after_the_save_is_current(self):
        self.assertEqual(compare("2026-10-13T10:30:00Z", self.SAVED)["state"], CURRENT)

    def test_a_file_uploaded_at_the_moment_of_the_save_is_current(self):
        self.assertEqual(compare("2026-10-13T10:00:00Z", self.SAVED)["state"], CURRENT)

    def test_a_file_uploaded_before_the_save_is_out_of_date(self):
        self.assertEqual(compare("2026-10-13T09:59:59Z", self.SAVED)["state"], STALE)

    def test_zones_are_compared_as_instants(self):
        self.assertEqual(compare("2026-10-13T11:30:00+02:00", self.SAVED)["state"], STALE)   # 09:30 UTC

    def test_unsaved_changes_are_never_reported_current(self):
        self.assertEqual(compare("2026-10-14T10:00:00Z", dict(self.SAVED, unsaved=True))["state"], UNSAVED)

    def test_a_save_that_cannot_be_dated_cannot_be_told(self):
        answer = compare("2026-10-13T10:30:00Z", {"saved": None, "unsaved": False, "reason": "Not saved to Fusion."})
        self.assertEqual((answer["state"], answer["message"]), (UNKNOWN, "Not saved to Fusion."))

    def test_an_unreadable_upload_time_cannot_be_told(self):
        self.assertEqual(compare("", self.SAVED)["state"], UNKNOWN)

    def test_the_message_names_the_document_that_decides(self):
        source = dict(self.SAVED, saved_in="The design Universal Joint", unsaved_in="The drawing PN-1")
        self.assertIn("the design Universal Joint", compare("2026-10-13T10:30:00Z", source)["message"])
        self.assertIn("The design Universal Joint was saved", compare("2026-10-13T09:00:00Z", source)["message"])
        self.assertTrue(compare("2026-10-13T10:30:00Z", dict(source, unsaved=True))["message"].startswith("The drawing PN-1 has changes"))


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from src.fm.client import FmApiError
from src.fm.refusal import FmRefused, read_refusal

KNOWN = {"TITLE", "PLANNED_DATE_1", "PLANNED_DATE_10", "SINGLE_LINE_TEXT_FIELD"}


def refused(body, status=400):
    return FmApiError("HTTP 400 ...", status, body if isinstance(body, str) else json.dumps(body))


class ReadRefusalTests(unittest.TestCase):
    def test_a_message_in_an_entry_that_names_a_field_belongs_to_that_field(self):
        body = {"message": "Validation failed", "errors": [{"field": "TITLE", "message": "Title is required"},
                                                           {"__self__": "/api/v3/workspaces/1/views/1/fields/SINGLE_LINE_TEXT_FIELD", "message": "Not unique"}]}
        found = read_refusal(refused(body), KNOWN, "General")
        self.assertIsInstance(found, FmRefused)
        self.assertEqual(found.fields, {"TITLE": "Title is required", "SINGLE_LINE_TEXT_FIELD": "Not unique"})
        self.assertEqual((str(found), found.status), ("Validation failed", 400))

    def test_a_message_that_names_a_field_as_a_word_belongs_to_it_and_the_longest_id_wins(self):
        found = read_refusal(refused({"errors": [{"message": "Field PLANNED_DATE_10 cannot be before PLANNED_DATE_9"}]}), KNOWN, "General")
        self.assertEqual(found.fields, {"PLANNED_DATE_10": "Field PLANNED_DATE_10 cannot be before PLANNED_DATE_9"})
        self.assertEqual(str(found), "General")   # nothing was said of the form as a whole

    def test_a_message_that_names_no_field_is_for_the_form_as_a_whole(self):
        found = read_refusal(refused({"message": "You may not add items here"}), KNOWN, "General")
        self.assertEqual((str(found), found.fields), ("You may not add items here", {}))

    def test_a_refusal_with_no_body_or_no_json_or_no_messages_is_left_as_it_was(self):
        for body in ("", "<html>bad gateway</html>", {"status": 400}, "[]"):
            with self.subTest(body=body):
                exc = refused(body)
                self.assertIs(read_refusal(exc, KNOWN, "General"), exc)

    def test_an_id_inside_a_longer_word_is_not_a_field(self):
        found = read_refusal(refused({"message": "MY_TITLE_2 is wrong"}), KNOWN, "General")
        self.assertEqual(found.fields, {})


if __name__ == "__main__":
    unittest.main()

"""``ItemService.urn``: one read of the item, giving its urn."""

import unittest
from unittest import mock

from src.fm.client import FmApiError
from src.fm.items import ItemService


class UrnTests(unittest.TestCase):
    def service(self, answer):
        client = mock.Mock()
        client.get_json.return_value = answer
        return ItemService(client), client

    def test_a_dict_answer_gives_its_urn_from_one_read(self):
        service, client = self.service({"urn": "urn:adsk.plm:tenant.workspace.item:ACME.57.1"})
        self.assertEqual(service.urn("57", "1"), "urn:adsk.plm:tenant.workspace.item:ACME.57.1")
        client.get_json.assert_called_once_with("/api/v3/workspaces/57/items/1")

    def test_an_answer_with_no_urn_gives_an_empty_text(self):
        self.assertEqual(self.service({"title": "x"})[0].urn("57", "1"), "")

    def test_item_gives_the_answer_as_it_is(self):
        service, client = self.service({"urn": "u", "title": "x"})
        self.assertEqual(service.item("57", "1"), {"urn": "u", "title": "x"})
        client.get_json.assert_called_once_with("/api/v3/workspaces/57/items/1")

    def test_an_answer_that_is_not_an_object_is_an_error(self):
        with self.assertRaises(FmApiError) as raised:
            self.service([])[0].urn("57", "1")
        self.assertIn("gave no item 1", str(raised.exception))

    def test_item_with_an_answer_that_is_not_an_object_is_an_error(self):
        for answer in ([], "x", None):
            with self.subTest(answer=answer), self.assertRaises(FmApiError) as raised:
                self.service(answer)[0].item("57", "1")
            self.assertIn("gave no item 1", str(raised.exception))

    def test_read_named_gives_the_descriptor_and_fields_from_one_read(self):
        service, client = self.service({"title": "PN-1 - Axle", "sections": [{"fields": [
            {"__self__": "/api/v3/workspaces/57/items/1/views/1/fields/PRIMARY", "value": "x"}]}]})
        self.assertEqual(service.read_named("57", "1"), ("PN-1 - Axle", {"PRIMARY": "x"}))
        client.get_json.assert_called_once_with("/api/v3/workspaces/57/items/1")

    def test_read_named_with_an_answer_that_is_not_an_object_is_an_error(self):
        for answer in ([], "x", None):
            with self.subTest(answer=answer), self.assertRaises(FmApiError):
                self.service(answer)[0].read_named("57", "1")


if __name__ == "__main__":
    unittest.main()

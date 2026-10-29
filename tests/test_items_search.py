"""Searching Fusion Manage for items by item number: the query that is sent, and the hits that come back."""

import unittest
from urllib.parse import parse_qs, urlparse

from src.fm.items import FIND_PAGE, ItemService, item_id_of, number_key


class Client:
    def __init__(self, *answers):
        self.answers, self.paths = list(answers), []

    def get_json(self, path, accept="application/json"):
        self.paths.append(path)
        return self.answers.pop(0)


def query_of(path):
    return parse_qs(urlparse(path).query)["query"][0]


def row(item_id, descriptor):
    return {"__self__": f"/api/v3/workspaces/242/items/{item_id}", "descriptor": descriptor}


class QueryTests(unittest.TestCase):
    def test_the_number_is_searched_as_a_quoted_descriptor_in_the_workspace(self):
        client = Client({"items": []})
        ItemService(client).search("242", "PN-1")
        self.assertEqual(query_of(client.paths[0]), 'itemDescriptor="PN-1" AND (workspaceId=242)')

    def test_a_quote_or_backslash_in_a_number_cannot_end_the_term(self):
        client = Client({"items": []})
        ItemService(client).search("242", 'PN-1" OR (workspaceId=1\\')
        self.assertEqual(query_of(client.paths[0]), 'itemDescriptor="PN-1 OR (workspaceId=1" AND (workspaceId=242)')

    def test_several_numbers_are_one_search_and_blank_ones_are_left_out(self):
        client = Client({"items": []})
        ItemService(client).find_many("242", ["A-1", "  ", "B-2"])
        self.assertEqual(query_of(client.paths[0]), '(itemDescriptor="A-1" OR itemDescriptor="B-2") AND (workspaceId=242)')

    def test_nothing_to_look_for_asks_nothing(self):
        client = Client()
        self.assertEqual(ItemService(client).find_many("242", ["", " "]), {})
        self.assertEqual(ItemService(client).search("242", ""), [])
        self.assertEqual(client.paths, [])


class PagingTests(unittest.TestCase):
    def test_the_next_page_is_asked_for_while_the_total_says_there_is_more(self):
        client = Client({"totalCount": FIND_PAGE + 1, "items": [row(1, "A-1 - One")] * FIND_PAGE}, {"totalCount": FIND_PAGE + 1, "items": [row(2, "A-1 - Two")]})
        found = ItemService(client).find_many("242", ["A-1"])
        self.assertEqual(len(found["a-1"]), FIND_PAGE + 1)
        self.assertEqual([parse_qs(urlparse(p).query)["page"][0] for p in client.paths], ["1", "2"])

    def test_a_total_that_is_not_a_number_ends_the_paging(self):
        client = Client({"totalCount": "many", "items": [row(1, "A-1 - One")]})
        ItemService(client).find_many("242", ["A-1"])
        self.assertEqual(len(client.paths), 1)


class HelperTests(unittest.TestCase):
    def test_the_item_is_named_by_the_first_field_that_has_an_id(self):
        self.assertEqual(item_id_of({"__self__": "x", "link": "/api/v3/workspaces/1/items/7"}), "7")
        self.assertEqual(item_id_of({"urn": None}), "")

    def test_a_number_is_compared_trimmed_and_in_lower_case(self):
        self.assertEqual(number_key("  PN-1 - Axle"), "pn-1")


if __name__ == "__main__":
    unittest.main()

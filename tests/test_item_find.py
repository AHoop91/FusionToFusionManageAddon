"""One search for the items of several item numbers, carrying the item details."""

import unittest
from urllib.parse import parse_qs, urlparse

from src.fm.items import ITEMS_BULK, ItemService


def row(item_id, descriptor, **fields):
    return {"__self__": f"/api/v3/workspaces/242/items/{item_id}", "descriptor": descriptor,
            "sections": [{"fields": [{"__self__": f"/api/v3/workspaces/242/items/{item_id}/views/1/fields/{name}", "value": value}
                                     for name, value in fields.items()]}]}


class FakeClient:
    def __init__(self, *pages):
        self.pages, self.asked = list(pages), []

    def get_json(self, path, accept="application/json"):
        self.asked.append((path, accept))
        return self.pages.pop(0)


class FindManyTests(unittest.TestCase):
    def test_one_search_for_every_number_asks_for_the_details(self):
        client = FakeClient({"totalCount": 2, "items": [row(1, "PN-1 - Bracket", NUMBER="PN-1"), row(2, "PN-2 - Plate", NUMBER="PN-2")]})
        found = ItemService(client).find_many("242", ["PN-1", "PN-2"])
        self.assertEqual(len(client.asked), 1)
        path, accept = client.asked[0]
        self.assertEqual(accept, ITEMS_BULK)
        self.assertEqual(parse_qs(urlparse(path).query)["query"], ['(itemDescriptor="PN-1" OR itemDescriptor="PN-2") AND (workspaceId=242)'])
        self.assertEqual(found["pn-1"], [{"id": "1", "descriptor": "PN-1 - Bracket", "values": {"NUMBER": "PN-1"}}])
        self.assertEqual(found["pn-2"][0]["id"], "2")

    def test_a_number_nothing_was_found_for_is_left_out(self):
        client = FakeClient({"totalCount": 1, "items": [row(1, "PN-1 - Bracket", NUMBER="PN-1")]})
        self.assertEqual(list(ItemService(client).find_many("242", ["PN-1", "PN-2"])), ["pn-1"])

    def test_a_hit_for_some_other_number_is_ignored(self):
        client = FakeClient({"totalCount": 1, "items": [row(5, "PN-10 - Other", NUMBER="PN-10")]})
        self.assertEqual(ItemService(client).find_many("242", ["PN-1"]), {})

    def test_two_items_with_one_number_are_both_kept(self):
        client = FakeClient({"totalCount": 2, "items": [row(1, "PN-1 - A"), row(2, "PN-1 - B")]})
        self.assertEqual([h["id"] for h in ItemService(client).find_many("242", ["PN-1"])["pn-1"]], ["1", "2"])

    def test_the_next_page_is_read_while_there_is_more(self):
        first = [row(n, f"PN-{n} - x") for n in range(100)]
        client = FakeClient({"totalCount": 101, "items": first}, {"totalCount": 101, "items": [row(100, "PN-100 - x")]})
        found = ItemService(client).find_many("242", [f"PN-{n}" for n in range(101)])
        self.assertEqual(len(client.asked), 2)
        self.assertIn("offset=100", client.asked[1][0])
        self.assertEqual(len(found), 101)

    def test_an_answer_without_details_still_gives_the_ids(self):
        client = FakeClient({"totalCount": 1, "items": [{"__self__": "/api/v3/workspaces/242/items/7", "descriptor": "PN-1"}]})
        self.assertEqual(ItemService(client).find_many("242", ["PN-1"])["pn-1"][0]["values"], {})

    def test_nothing_is_asked_for_no_numbers(self):
        client = FakeClient()
        self.assertEqual(ItemService(client).find_many("242", ["", " "]), {})
        self.assertEqual(client.asked, [])


if __name__ == "__main__":
    unittest.main()

"""Where an item is used: the parents that hold it, one level at a time."""

import unittest

from src.fm.bom import split_title
from src.fm.client import FmApiError
from src.fm.where_used import WhereUsedService, _one_level, parse_where_used

BASE = "https://acme.autodeskplm360.net"


def node(urn, title, *fields):
    return {"item": {"urn": urn, "title": title, "version": "B", "link": "/api/v3/workspaces/57/items/" + urn[-1]},
            "fields": [{"title": t, "value": v} for t, v in fields]}


def answer(nodes, edges):
    return {"nodes": nodes, "edges": edges}


class ParseTests(unittest.TestCase):
    def test_a_row_for_each_parent_with_its_fields_as_columns_in_the_order_first_seen(self):
        data = answer([node("u:1", "A-1 - Top [REV:w]", ("DESCRIPTOR", "x"), ("Status", "Open"), ("Owner", None)), node("u:2", "A-2 - Sub", ("Owner", "Pat"), ("Cost", 3))],
                      [{"child": "u:1", "edgeLink": "/api/v3/workspaces/57/items/1/where-used"}, {"child": "u:2"}])
        found = parse_where_used(data, BASE)
        self.assertEqual(found["columns"], ["Status", "Owner", "Cost"])
        first, second = found["rows"]
        self.assertEqual((first["number"], first["name"], first["version"]), ("A-1", "Top", "B"))
        self.assertEqual(first["fields"], {"Status": "Open", "Owner": ""})
        self.assertEqual(first["up"], "/api/v3/workspaces/57/items/1/where-used?depth=1")
        self.assertEqual((second["up"], second["fields"]["Cost"]), ("", "3"))

    def test_an_edge_to_an_item_that_is_not_a_node_is_left_out(self):
        self.assertEqual(parse_where_used(answer([node("u:1", "A - B")], [{"child": "u:9"}, {"child": None}]), BASE)["rows"], [])

    def test_nothing_holding_the_item_is_empty(self):
        self.assertEqual(parse_where_used(None, BASE), {"rows": [], "columns": []})

    def test_an_answer_of_the_wrong_shape_is_an_error(self):
        for data in ({}, {"nodes": []}, {"nodes": "x", "edges": []}, "x", []):
            with self.subTest(data=data):
                with self.assertRaises(FmApiError):
                    parse_where_used(data, BASE)


class OneLevelTests(unittest.TestCase):
    def test_the_link_asks_for_one_level(self):
        self.assertEqual(_one_level("/w/1/where-used"), "/w/1/where-used?depth=1")
        self.assertEqual(_one_level("/w/1/where-used?depth=5"), "/w/1/where-used?depth=1")
        self.assertEqual(_one_level("/w/1/where-used?depth=5&x=1"), "/w/1/where-used?x=1&depth=1")
        self.assertEqual(_one_level(""), "")


class Client:
    base_url = BASE

    def __init__(self):
        self.paths = []

    def get_json(self, path, accept="application/json"):
        self.paths.append(path)
        return None


class ReadTests(unittest.TestCase):
    def test_the_item_is_asked_one_level_up_by_default(self):
        client = Client()
        WhereUsedService(client).read("57", "9")
        self.assertEqual(client.paths, ["/api/v3/workspaces/57/items/9/where-used?depth=1"])

    def test_the_next_level_is_read_from_the_link_the_page_gives(self):
        client = Client()
        WhereUsedService(client).read("57", "9", "/api/v3/workspaces/57/items/4/where-used?depth=1")
        self.assertEqual(client.paths, ["/api/v3/workspaces/57/items/4/where-used?depth=1"])

    def test_an_address_outside_the_api_is_refused_before_anything_is_asked(self):
        client = Client()
        for up in ("https://evil.example.com/x", "/other/path", "//evil.example.com"):
            with self.subTest(up=up):
                with self.assertRaises(ValueError):
                    WhereUsedService(client).read("57", "9", up)
        self.assertEqual(client.paths, [])


class SplitTitleTests(unittest.TestCase):
    def test_the_number_and_name_without_the_revision(self):
        self.assertEqual(split_title("9410-306 - STEP [REV:w]"), ("9410-306", "STEP"))

    def test_a_title_with_no_separator_is_all_name(self):
        self.assertEqual(split_title("Loose part [REV:A]"), ("", "Loose part"))


if __name__ == "__main__":
    unittest.main()

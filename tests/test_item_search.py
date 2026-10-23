"""Reading search answers for the Add Items picker."""

import unittest

from src.fm.item_search import parse_members, parse_search


class ParseSearchTests(unittest.TestCase):
    def test_a_hit_becomes_an_item_with_a_linkable_row(self):
        data = {"totalCount": 2, "items": [{"__self__": "/api/v3/workspaces/57/items/15719",
                                            "descriptor": "WG1-6073 - HEX NUT [REV:B]"}]}
        page = parse_search(data, "57", "14669")
        item = page["items"][0]
        self.assertEqual((page["total"], len(page["items"])), (2, 1))
        self.assertEqual((item["id"], item["number"], item["name"], item["version"]), ("15719", "WG1-6073", "HEX NUT", "B"))
        self.assertEqual(item["linkable"]["__self__"], "/api/v3/workspaces/57/items/14669/views/5/linkable-items/15719")
        self.assertEqual(item["linkable"]["item"]["link"], "/api/v3/workspaces/57/items/15719")
        self.assertIn("{{tenant}}.57.14669.5.15719", item["linkable"]["urn"])

    def test_a_design_not_in_fusion_manage_has_no_linkable_row_yet(self):
        data = {"totalCount": 1, "items": [{"__self__": "/api/v3/workspaces/57/items/15719", "descriptor": "WG1-6073 - HEX NUT"}]}
        item = parse_search(data, "57", "")["items"][0]
        self.assertEqual(item["id"], "15719")
        self.assertIsNone(item["linkable"])   # the publish writes the row, with the new item's id, when it adds the line

    def test_a_revision_is_the_letter_alone_however_it_is_sent(self):
        for sent in ("W", "REV:W", "[REV:W]"):
            data = {"items": [{"__self__": "/api/v3/workspaces/57/items/1", "descriptor": "A - B", "version": sent}]}
            self.assertEqual(parse_search(data, "57", "9")["items"][0]["version"], "W", sent)

    def test_the_parent_item_is_left_out(self):
        data = {"totalCount": 1, "items": [{"link": "/api/v3/workspaces/57/items/14669", "descriptor": "A - B"}]}
        page = parse_search(data, "57", "14669")
        self.assertEqual((page["items"], page["raw"]), ([], 1))

    def test_rubbish_gives_an_empty_page(self):
        self.assertEqual(parse_search("x", "57", "1"), {"total": 0, "raw": 0, "items": []})


class ParseMembersTests(unittest.TestCase):
    def test_ids_and_numbers_of_the_nodes(self):
        data = {"nodes": [{"item": {"link": "/api/v3/workspaces/57/items/9", "title": "N1 - One [REV:A]"}}, {"item": {}}]}
        self.assertEqual(parse_members(data), {"ids": ["9"], "numbers": ["N1"]})
        self.assertEqual(parse_members(None), {"ids": [], "numbers": []})


if __name__ == "__main__":
    unittest.main()

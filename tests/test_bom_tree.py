"""The whole BOM of an item as one tree, with the item id and line id of each line (the MBOM the structure viewer starts from)."""

import unittest

from src.fm.bom import BomService, build_tree, parse_bom
from src.fm.client import FmApiError


def urn(item):
    return f"urn:adsk.plm:tenant.workspace.item:ACME.57.{item}"


def node(item, title):
    return {"item": {"urn": urn(item), "title": title}}


def edge(parent, child, number, quantity="1", edge_id=None):
    return {"parent": urn(parent), "child": urn(child), "itemNumber": number, "edgeId": edge_id or f"e{parent}-{child}",
            "fields": [{"metaData": {"link": "/api/v3/workspaces/57/views/1/fields/103"}, "value": quantity}]}


NODES = [node(1, "TOP-M - Top [REV:w]"), node(2, "ASM - Assembly [REV:w]"), node(3, "PART - Part [REV:w]"), node(4, "PH - Phantom [REV:w]")]
EDGES = [edge(1, 2, 1, "2"), edge(1, 4, 2), edge(2, 3, 1, "4"), edge(4, 3, 1), edge(4, 2, 2)]
ANSWER = {"nodes": NODES, "edges": EDGES}


class Client:
    def __init__(self, answer):
        self.answer, self.paths = answer, []

    def get_json(self, path, accept=None):
        self.paths.append(path)
        return self.answer


class BomTreeTests(unittest.TestCase):
    def test_lines_carry_the_id_of_their_item(self):
        lines = parse_bom(ANSWER)
        self.assertEqual([(l["number"], l["item_id"]) for l in lines["TOP-M"]], [("ASM", "2"), ("PH", "4")])

    def test_a_urn_that_is_not_an_items_gives_no_item_id_to_the_plain_parse(self):
        lines = parse_bom({"nodes": [{"item": {"urn": "u1", "title": "A - Top"}}, {"item": {"urn": "u2", "title": "B - Part"}}],
                           "edges": [{"parent": "u1", "child": "u2"}]})
        self.assertEqual(lines["A"][0]["item_id"], "")

    def test_the_tree_nests_to_every_depth_and_an_item_in_two_places_has_its_lines_in_both(self):
        tree = build_tree(parse_bom(ANSWER), ANSWER, "1", 10)
        self.assertEqual((tree["number"], tree["name"], tree["item_id"]), ("TOP-M", "Top", "1"))
        asm, phantom = tree["children"]
        self.assertEqual([(c["number"], c["quantity"], c["item_id"], c["edge_id"]) for c in asm["children"]], [("PART", "4", "3", "e2-3")])
        self.assertEqual([c["number"] for c in phantom["children"]], ["PART", "ASM"])
        self.assertEqual([c["number"] for c in phantom["children"][1]["children"]], ["PART"], "ASM under the phantom has its own lines too")

    def test_an_item_inside_itself_raises(self):
        looped = {"nodes": NODES[:2], "edges": [edge(1, 2, 1), edge(2, 1, 1)]}
        with self.assertRaises(FmApiError):
            build_tree(parse_bom(looped), looped, "1", 10)

    def test_a_line_cut_at_the_last_level_is_marked_when_the_answer_shows_it_has_lines(self):
        tree = build_tree(parse_bom(ANSWER), ANSWER, "1", 2)
        asm, phantom = tree["children"]
        self.assertEqual([(c["number"], c["children"], c.get("cut")) for c in asm["children"]], [("PART", [], None)])
        self.assertEqual([(c["number"], c.get("cut")) for c in phantom["children"]], [("PART", None), ("ASM", True)])
        self.assertNotIn("cut", asm)

    def test_a_line_whose_parent_or_child_has_no_item_number_raises(self):
        nameless = {"nodes": [node(1, "TOP - Top"), {"item": {"urn": urn(2), "title": ""}}], "edges": [edge(1, 2, 1)]}
        with self.assertRaises(FmApiError):
            build_tree(parse_bom(nameless), nameless, "1", 10)

    def test_a_tree_with_too_many_lines_raises_and_a_diamond_is_counted_not_hidden(self):
        levels = 12   # each level has two items, both under both of the level above: 2 ** levels paths
        nodes = [node(0, "TOP - Top")] + [node(10 * n + k, f"L{n}{k} - Level") for n in range(1, levels + 1) for k in (1, 2)]
        edges = [edge(0, 11, 1), edge(0, 12, 2)] + [edge(10 * n + a, 10 * (n + 1) + b, b) for n in range(1, levels) for a in (1, 2) for b in (1, 2)]
        answer = {"nodes": nodes, "edges": edges}
        with self.assertRaises(FmApiError):
            build_tree(parse_bom(answer), answer, "0", 20, cap=1000)
        self.assertEqual(len(build_tree(parse_bom(answer), answer, "0", 3)["children"]), 2)

    def test_an_answer_without_the_item_or_a_line_without_an_item_id_raises(self):
        with self.assertRaises(FmApiError):
            build_tree(parse_bom(ANSWER), ANSWER, "99", 10)
        broken = {"nodes": [{"item": {"urn": urn(1), "title": "A - Top"}}, {"item": {"urn": "u2", "title": "B - Part"}}], "edges": [{"parent": urn(1), "child": "u2"}]}
        with self.assertRaises(FmApiError):
            build_tree(parse_bom(broken), broken, "1", 10)

    def test_the_service_reads_the_working_bom_to_the_depth_asked(self):
        client = Client(ANSWER)
        tree = BomService(client).tree("57", "1", 10)
        self.assertEqual(len(tree["children"]), 2)
        self.assertIn("/workspaces/57/items/1/bom?depth=10", client.paths[0])
        self.assertIn("revisionBias=working&rootId=1", client.paths[0])


if __name__ == "__main__":
    unittest.main()

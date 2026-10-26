"""Lines of items that share an item number are told apart by name."""

import unittest

from src.sync.bom_compare import EXTRA, MATCH, compare_bom


def row(number, name, quantity="1"):
    return {"level": 0, "item_number": number, "part_number": number, "name": name, "quantity": quantity}


def line(number, name, sequence, quantity="1"):
    return {"number": number, "name": name, "quantity": quantity, "sequence": sequence, "edge_id": "e" + sequence}


class LinesOfItemsThatShareANumberTests(unittest.TestCase):
    BOM = {"TOP": [line("PN-6", "24mm Bearing", "7"), line("PN-6", "End Cap Pulley Side", "6")]}

    def test_the_line_named_like_the_design_line_is_taken(self):
        result = compare_bom([row("PN-6", "End Cap Pulley Side")], "TOP", self.BOM)
        self.assertEqual(result[0]["status"], MATCH)
        self.assertEqual(result[0]["fm_edge_id"], "e6")

    def test_the_other_line_is_left_over(self):
        result = compare_bom([row("PN-6", "End Cap Pulley Side")], "TOP", self.BOM)
        self.assertEqual([r["name"] for r in result if r["status"] == EXTRA], ["24mm Bearing"])

    def test_without_a_matching_name_the_first_line_is_taken(self):
        result = compare_bom([row("PN-6", "Something Else")], "TOP", self.BOM)
        self.assertEqual(result[0]["fm_edge_id"], "e7")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest import mock

from src.sync import bom_compare
from src.sync.bom_compare import DIFFERING, read_and_compare_bom


def row(number, level=0, quantity="1", sequence=""):
    return {"level": level, "item_number": number, "part_number": number, "quantity": quantity, "sequence": sequence}


def line(number, quantity="1", sequence=""):
    return {"number": number, "quantity": quantity, "name": "", "sequence": sequence}


class ReadAndCompareBomTests(unittest.TestCase):
    def compared(self, rows, fm_bom):
        with mock.patch.object(bom_compare, "BomService") as service:
            service.return_value.read.return_value = fm_bom
            result = read_and_compare_bom(rows, "TOP", mock.Mock(), "242", "9")
        return result, service.return_value.read

    def differing(self, result):
        return [r["item_number"] for r in result if r["status"] in DIFFERING]

    def test_components_under_the_same_parent_in_the_same_quantity_are_up_to_date(self):
        result, _ = self.compared([row("A"), row("B", quantity="2")], {"TOP": [line("A"), line("B", "2")]})
        self.assertEqual(self.differing(result), [])

    def test_a_component_not_under_that_parent_is_out_of_date(self):
        result, _ = self.compared([row("A"), row("B", 1)], {"TOP": [line("A"), line("B")]})   # B is under A in the design, under TOP in Fusion Manage
        self.assertEqual(self.differing(result), ["B"])

    def test_another_quantity_is_out_of_date(self):
        result, _ = self.compared([row("A", quantity="3")], {"TOP": [line("A", "1")]})
        self.assertEqual(self.differing(result), ["A"])

    def test_a_line_only_fusion_manage_has_is_not_a_difference(self):
        result, _ = self.compared([row("A")], {"TOP": [line("A"), line("OIL")]})
        self.assertEqual(self.differing(result), [])

    def test_a_new_line_and_a_fusion_manage_only_line_at_the_same_position_are_paired(self):
        result, _ = self.compared([row("A", sequence=1), row("GASKET", sequence=2)],
                                  {"TOP": [line("A", sequence="1"), line("SEAL", sequence="2")]})
        pairs = {r["item_number"]: r["pair"] for r in result if r["status"] in ("new", "extra")}
        self.assertEqual(pairs, {"GASKET": "SEAL", "SEAL": "GASKET"})

    def test_a_line_removed_at_one_position_and_one_added_at_another_are_not_paired(self):
        result, _ = self.compared([row("A", sequence=10), row("GASKET", sequence=11)],
                                  {"TOP": [line("A", sequence="10"), line("OIL", sequence="12")]})   # no line 11 in Fusion Manage: oil is its own
        self.assertEqual([(r["item_number"], r["status"], r.get("pair", "")) for r in result],
                         [("A", "match", ""), ("GASKET", "new", ""), ("OIL", "extra", "")])

    def test_a_line_without_an_item_number_and_the_lines_below_it_are_skipped(self):
        rows = [row("A"), row("", 0), row("C", 1), row("D", 2), row("E", 0)]   # C and D hang under the numberless line
        result, _ = self.compared(rows, {"TOP": [line("A"), line("E")]})
        self.assertEqual([(r["item_number"], r["status"]) for r in result],
                         [("A", "match"), ("", "skipped"), ("C", "skipped"), ("D", "skipped"), ("E", "match")])
        self.assertEqual(self.differing(result), [])

    def test_a_skipped_line_takes_no_fusion_manage_line(self):
        result, _ = self.compared([row("")], {"TOP": [line("A")]})
        self.assertEqual([(r["item_number"], r["status"]) for r in result], [("", "skipped"), ("A", "extra")])

    def test_the_bom_is_read_deep_enough_for_the_whole_tree(self):
        _, read = self.compared([row("A"), row("B", 1), row("C", 2)], {})
        read.assert_called_once_with("242", "9", 3)


if __name__ == "__main__":
    unittest.main()

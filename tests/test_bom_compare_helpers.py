"""The small rules inside the BOM comparison: positions, quantities, skipped lines, pairing and ordering of extras."""

import unittest
from unittest import mock

from src.sync import bom_compare
from src.sync.bom_compare import (CHANGED, EXTRA, MATCH, NEW, NO_NUMBER, PARENT_SKIPPED, _pair_by_position, _position,
                                  _same_quantity, compare_bom, mark_skipped)


def row(number, level=0, sequence="", quantity="1", name=""):
    return {"level": level, "item_number": number, "sequence": sequence, "quantity": quantity, "name": name or number}


def line(number, sequence="", quantity="1", name=""):
    return {"number": number, "name": name or number, "quantity": quantity, "sequence": sequence, "edge_id": "e" + number}


def summary(result):
    return [(r["item_number"], r["status"]) for r in result]


class PositionTests(unittest.TestCase):
    def test_a_whole_number_reads_the_same_as_text_and_as_a_number(self):
        self.assertEqual([_position(11), _position("11"), _position("11.0"), _position(" 011 ")], ["11"] * 4)

    def test_no_position_and_zero_are_empty(self):
        self.assertEqual([_position(None), _position(""), _position("0")], ["", "", ""])

    def test_words_that_parse_as_floats_are_kept_as_text(self):
        self.assertEqual([_position("nan"), _position("inf")], ["nan", "inf"])


class QuantityTests(unittest.TestCase):
    def test_numbers_compare_as_numbers(self):
        self.assertTrue(_same_quantity("2", "2.0"))
        self.assertFalse(_same_quantity("1", "2"))

    def test_text_compares_as_text(self):
        self.assertTrue(_same_quantity("nan", "nan"))
        self.assertTrue(_same_quantity(" a ", "a"))
        self.assertFalse(_same_quantity("a", "b"))

    def test_a_number_and_text_differ(self):
        self.assertFalse(_same_quantity("1", "one"))


class MarkSkippedTests(unittest.TestCase):
    def test_a_line_without_a_number_and_the_lines_below_it_are_skipped(self):
        rows = [row("A"), row("", 1), row("B", 2), row("C", 3), row("D", 1), row("E")]
        self.assertEqual([r.get("skip") for r in mark_skipped(rows)], [None, NO_NUMBER, PARENT_SKIPPED, PARENT_SKIPPED, None, None])

    def test_marking_twice_gives_the_same_rows(self):
        once = mark_skipped([row(""), row("B", 1)])
        self.assertEqual(mark_skipped(once), once)


class PairByPositionTests(unittest.TestCase):
    def test_lines_at_the_same_position_pair(self):
        self.assertEqual(_pair_by_position([(5, "11")], [(0, "12"), (1, "11")]), [(5, 1)])

    def test_a_position_the_other_side_does_not_use_stays_unpaired(self):
        self.assertEqual(_pair_by_position([(5, "12")], [(0, "11")]), [])

    def test_lines_without_a_position_pair_in_order(self):
        self.assertEqual(_pair_by_position([(5, ""), (6, None)], [(0, ""), (1, "")]), [(5, 0), (6, 1)])

    def test_a_line_with_a_position_does_not_pair_with_one_without(self):
        self.assertEqual(_pair_by_position([(5, "11")], [(0, "")]), [])


class CompareBomTests(unittest.TestCase):
    def test_a_paired_extra_sits_before_its_new_line_and_below_their_siblings_stay_put(self):
        fm = {"TOP": [line("A", "10"), line("SEAL", "11")]}
        result = compare_bom([row("A", sequence="10"), row("GASKET", sequence="11"), row("Z", sequence="12")], "TOP", fm)
        self.assertEqual(summary(result), [("A", MATCH), ("SEAL", EXTRA), ("GASKET", NEW), ("Z", NEW)])
        self.assertEqual((result[1]["pair"], result[2]["pair"]), ("GASKET", "SEAL"))

    def test_unpaired_extras_go_after_the_parents_children_and_their_subtrees(self):
        fm = {"TOP": [line("A", "10"), line("OIL", "99")]}
        result = compare_bom([row("A", sequence="10"), row("B", 1)], "TOP", fm)
        self.assertEqual(summary(result), [("A", MATCH), ("B", NEW), ("OIL", EXTRA)])

    def test_extras_of_a_nested_parent_stay_with_it(self):
        fm = {"TOP": [line("A", "10")], "A": [line("X", "1"), line("OLD", "2")]}
        result = compare_bom([row("A", sequence="10"), row("X", 1, "1"), row("NEWER", 1, "2")], "TOP", fm)
        self.assertEqual([(r["item_number"], r["level"]) for r in result],
                         [("A", 0), ("X", 1), ("OLD", 1), ("NEWER", 1)])

    def test_a_changed_quantity_is_changed(self):
        result = compare_bom([row("A", quantity="3")], "TOP", {"TOP": [line("A", quantity="2")]})
        self.assertEqual(summary(result), [("A", CHANGED)])
        self.assertEqual(result[0]["fm_quantity"], "2")

    def test_numbers_are_compared_without_case_or_outer_spaces(self):
        result = compare_bom([row(" a ")], "top", {"TOP": [line("A")]})
        self.assertEqual(summary(result), [(" a ", MATCH)])

    def test_repeated_lines_pair_one_to_one(self):
        result = compare_bom([row("A"), row("A")], "TOP", {"TOP": [line("A")]})
        self.assertEqual(summary(result), [("A", MATCH), ("A", NEW)])

    def test_a_line_more_than_one_level_deeper_is_a_child_of_the_row_before(self):
        fm = {"TOP": [line("A")], "A": [line("B")]}
        result = compare_bom([row("A"), row("B", 3)], "TOP", fm)
        self.assertEqual(summary(result), [("A", MATCH), ("B", MATCH)])

    def test_a_line_with_missing_fields_does_not_break_the_comparison(self):
        result = compare_bom([row("A")], "TOP", {"TOP": [{"number": "A", "quantity": "1"}, {"number": "B"}]})
        self.assertEqual(summary(result), [("A", MATCH), ("B", EXTRA)])


class ReadAndCompareTests(unittest.TestCase):
    def read_depth(self, rows):
        with mock.patch.object(bom_compare, "BomService") as service:
            service.return_value.read.return_value = {}
            bom_compare.read_and_compare_bom(rows, "TOP", mock.Mock(), "242", "9", "bias")
        return service.return_value.read.call_args[0], service

    def test_the_bom_is_read_one_level_deeper_than_the_deepest_row(self):
        args, service = self.read_depth([row("A"), row("B", 1), row("C", 2)])
        self.assertEqual(args, ("242", "9", 3))
        self.assertEqual(service.call_args[0][1], "bias")

    def test_no_rows_still_reads_the_first_level(self):
        args, _ = self.read_depth([])
        self.assertEqual(args, ("242", "9", 1))


if __name__ == "__main__":
    unittest.main()

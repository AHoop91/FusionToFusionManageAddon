"""The Bill of Materials the Publish panel reads is compared with Fusion Manage a level at a time, asking as little as it can."""

import unittest
from unittest import mock

from src.sync import bom_levels
from src.sync.bom_compare import UNCOMPARED


def row(number, level=0):
    return {"level": level, "item_number": number, "part_number": number, "quantity": "1"}


class DesignNotInFusionManageTests(unittest.TestCase):
    """A design that is not in Fusion Manage has nothing to compare its lines with: they are left uncompared, with no request per line."""

    def test_no_item_for_the_design_leaves_its_lines_uncompared_and_asks_nothing_per_line(self):
        cfg = mock.Mock(workspace_id="242")
        fm = mock.Mock()
        with mock.patch.object(bom_levels, "read_and_compare_bom") as compare:
            data = bom_levels.compare_design_bom([row("A"), row("B", 1)], {"item_number": "TOP"}, cfg, fm, [])
        self.assertEqual([r["status"] for r in data["rows"]], [UNCOMPARED, UNCOMPARED])
        self.assertFalse(data["shared"])
        self.assertTrue(data["design_new"])   # the panel says "not in Fusion Manage yet" without waiting for the properties check
        compare.assert_not_called()
        self.assertEqual(fm.method_calls, [])

    def test_a_design_that_is_found_is_not_marked_new(self):
        cfg = mock.Mock(workspace_id="242")
        with mock.patch.object(bom_levels, "read_and_compare_bom", return_value=[]):
            data = bom_levels.compare_design_bom([row("A")], {"item_number": "TOP"}, cfg, mock.Mock(), [{"id": "1"}])
        self.assertNotIn("design_new", data)

    def test_several_matches_are_not_compared_with_any(self):
        cfg = mock.Mock(workspace_id="242")
        with mock.patch.object(bom_levels, "read_and_compare_bom") as compare:
            data = bom_levels.compare_design_bom([row("A")], {"item_number": "TOP"}, cfg, mock.Mock(), [{"id": "1"}, {"id": "2"}])
        self.assertTrue(data["shared"])
        compare.assert_not_called()

    def test_the_one_match_is_the_one_compared_with(self):
        cfg = mock.Mock(workspace_id="242")
        with mock.patch.object(bom_levels, "read_and_compare_bom", return_value=[]) as compare:
            data = bom_levels.compare_design_bom([row("A")], {"item_number": "TOP"}, cfg, mock.Mock(), [{"id": "2"}])
        self.assertEqual(data["fm_item_id"], "2")
        self.assertEqual(compare.call_args[0][3:], ("242", "2"))


class LevelUnderAnAssemblyTests(unittest.TestCase):
    """The lines under one opened assembly are compared with that assembly's Fusion Manage BOM alone."""

    def compared(self, rows, *, parent_number="ASM", skipped=False, design_in_fm=True, hits=None):
        cfg = mock.Mock(workspace_id="242")
        with mock.patch.object(bom_levels, "ItemService") as items, mock.patch.object(bom_levels, "read_and_compare_bom") as compare:
            items.return_value.search.return_value = [] if hits is None else hits
            compare.side_effect = lambda marked, *_: [{**r, "status": "skipped" if r.get("skip") else "match"} for r in marked]   # as compare_bom does
            data = bom_levels.compare_level(rows, parent_number, skipped, design_in_fm, cfg, mock.Mock())
        return [(r["item_number"], r["status"]) for r in data["rows"]], items, compare

    def test_lines_are_compared_with_the_bom_of_the_one_item_that_matches_the_assembly(self):
        result, _, compare = self.compared([row("A"), row("B")], hits=[{"id": "9"}])
        self.assertEqual(result, [("A", "match"), ("B", "match")])
        self.assertEqual(compare.call_args[0][1:], ("ASM", compare.call_args[0][2], "242", "9"))

    def test_an_assembly_fusion_manage_does_not_hold_has_every_line_new(self):
        result, _, compare = self.compared([row("A")], hits=[])
        self.assertEqual(result, [("A", "new")])
        compare.assert_not_called()

    def test_an_assembly_that_matches_several_items_is_left_uncompared(self):
        result, _, compare = self.compared([row("A")], hits=[{"id": "1"}, {"id": "2"}])
        self.assertEqual(result, [("A", UNCOMPARED)])
        compare.assert_not_called()

    def test_a_design_not_in_fusion_manage_asks_nothing(self):
        result, items, compare = self.compared([row("A")], design_in_fm=False)
        self.assertEqual(result, [("A", UNCOMPARED)])
        items.return_value.search.assert_not_called()
        compare.assert_not_called()

    def test_lines_of_a_skipped_assembly_are_skipped_and_nothing_is_asked(self):
        result, items, compare = self.compared([row("A"), row("")], parent_number="", skipped=True)
        self.assertEqual(result, [("A", "skipped"), ("", "skipped")])
        items.return_value.search.assert_not_called()
        compare.assert_not_called()

    def test_a_line_without_an_item_number_is_skipped_among_the_rest(self):
        result, _, _ = self.compared([row("A"), row("")], hits=[{"id": "9"}])
        self.assertEqual(result, [("A", "match"), ("", "skipped")])


if __name__ == "__main__":
    unittest.main()

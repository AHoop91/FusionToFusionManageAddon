"""The Bill of Materials the Publish panel reads is compared with Fusion Manage a level at a time, asking as little as it can."""

import unittest
from unittest import mock

from src.sync import bom_levels


def row(number, level=0):
    return {"level": level, "item_number": number, "part_number": number, "quantity": "1"}


class MarkDesignBomTests(unittest.TestCase):
    """The rows read under the design are marked where they cannot be published; Fusion Manage's own Bill of Materials is not asked for."""

    def test_the_unpublishable_lines_are_marked_and_the_rest_are_left_alone(self):
        data = bom_levels.mark_design_bom([row("A"), row("", 1), row("B")], {"item_number": "TOP"}, [{"id": "2"}])
        self.assertEqual([r.get("status") for r in data["rows"]], [None, "skipped", None])
        self.assertFalse(data["shared"])

    def test_a_design_that_is_not_in_fusion_manage_is_marked_the_same_way(self):
        data = bom_levels.mark_design_bom([row("A"), row("", 1)], {"item_number": "TOP"}, [])
        self.assertEqual([r.get("status") for r in data["rows"]], [None, "skipped"])
        self.assertFalse(data["shared"])

    def test_several_matches_say_the_number_is_shared(self):
        data = bom_levels.mark_design_bom([row("A")], {"item_number": "TOP"}, [{"id": "1"}, {"id": "2"}])
        self.assertTrue(data["shared"])

    def test_a_row_without_a_quantity_is_logged_without_failing(self):
        data = bom_levels.mark_design_bom([{"level": 0, "item_number": "A"}], {"item_number": "TOP"}, [])
        self.assertEqual(len(data["rows"]), 1)


class SearchDesignTests(unittest.TestCase):
    """Fusion Manage is searched for the design's number only when there is a workspace and a number to look for."""

    def test_searching_asks_nothing_without_a_workspace_or_a_number(self):
        fm = mock.Mock()
        self.assertEqual(bom_levels.search_design(fm, None, {"item_number": "TOP"}), [])
        self.assertEqual(bom_levels.search_design(fm, mock.Mock(workspace_id="242"), {"item_number": " "}), [])
        self.assertEqual(fm.method_calls, [])

    def test_searching_looks_the_number_up_in_the_workspace(self):
        with mock.patch.object(bom_levels, "ItemFinder") as items:
            items.return_value.search.return_value = [{"id": "1"}]
            found = bom_levels.search_design(mock.Mock(), mock.Mock(workspace_id="242"), {"item_number": " TOP "})
        self.assertEqual(found, [{"id": "1"}])
        items.return_value.search.assert_called_once_with("242", "TOP")


if __name__ == "__main__":
    unittest.main()

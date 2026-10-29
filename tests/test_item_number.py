"""A component is looked up by its item number alone."""

import unittest

from src.sync.item_number import item_number_of


class ItemNumberOfTests(unittest.TestCase):
    def test_the_number_is_the_item_number_never_the_part_number(self):
        self.assertEqual(item_number_of({"item_number": "A", "part_number": "B"}), "A")
        self.assertEqual(item_number_of({"item_number": "", "part_number": "B"}), "")
        self.assertEqual(item_number_of({"part_number": "B"}), "")

    def test_outer_spaces_are_dropped_and_inner_ones_kept(self):
        self.assertEqual(item_number_of({"item_number": "  PN 1 "}), "PN 1")

    def test_nothing_to_look_up_is_empty(self):
        self.assertEqual(item_number_of({}), "")
        self.assertEqual(item_number_of({"item_number": None}), "")
        self.assertEqual(item_number_of({"item_number": "   "}), "")

    def test_a_number_held_as_a_number_is_read_as_text(self):
        self.assertEqual(item_number_of({"item_number": 1042}), "1042")


if __name__ == "__main__":
    unittest.main()

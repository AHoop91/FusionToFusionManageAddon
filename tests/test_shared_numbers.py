"""Item numbers that more than one component of a publish carry."""

import unittest

from src.publish.shared_numbers import shared_numbers, shared_reason

SUMMARY = {"component_id": "root-id"}


def item(number, component_id, name="", root=False):
    return {"item_number": number, "id": component_id, "name": name, "root": root}


class SharedNumbersTests(unittest.TestCase):
    def test_components_with_one_number_are_shared(self):
        items = [item("PN-1", "a", "Bracket"), item("PN-1", "b", "Plate"), item("PN-2", "c", "Screw")]
        self.assertEqual(shared_numbers(items, SUMMARY), {"pn-1": ["Bracket", "Plate"]})

    def test_one_component_on_several_lines_is_not_shared(self):
        self.assertEqual(shared_numbers([item("PN-1", "a"), item("PN-1", "a")], SUMMARY), {})

    def test_the_case_and_spaces_of_a_number_do_not_tell_them_apart(self):
        self.assertEqual(list(shared_numbers([item("pn-1", "a"), item(" PN-1 ", "b")], SUMMARY)), ["pn-1"])

    def test_the_design_shares_its_number_with_a_line_that_carries_it(self):
        items = [item("TOP", "", "Top", root=True), item("TOP", "a", "Copy")]
        self.assertEqual(shared_numbers(items, SUMMARY), {"top": ["Top", "Copy"]})

    def test_an_item_without_a_number_shares_nothing(self):
        self.assertEqual(shared_numbers([item("", "a"), item("", "b")], SUMMARY), {})

    def test_the_reason_names_the_number_and_the_components(self):
        reason = shared_reason("PN-1", ["Bracket", "Plate"])
        self.assertIn("PN-1", reason)
        self.assertIn("Bracket, Plate", reason)
        self.assertTrue(reason.startswith("Skipped"))


if __name__ == "__main__":
    unittest.main()

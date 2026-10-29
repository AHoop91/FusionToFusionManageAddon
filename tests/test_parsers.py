"""Data Model answers parsed into rows: what is read, in what order, and that an answer of an unexpected shape reads as empty."""

import unittest

from src.fusion_mfg.parsers import parse_component, parse_properties, parse_structure, parse_summary

ODD = (None, "x", [], {"bulkModels": None}, {"bulkModels": "x"}, {"bulkModels": [None]}, {"bulkModels": [{"model": "x"}]},
       {"bulkModels": [{"model": {"component": "x"}}]})


def model(component):
    return {"bulkModels": [{"model": {"component": component}}]}


def relation(parent, child, sequence=1, **extra):
    return {"fromComponent": {"id": parent}, "toComponent": {"id": child, **extra}, "sequenceNumber": sequence}


class SummaryTests(unittest.TestCase):
    def test_the_fields_of_the_root_component(self):
        data = model({"id": "c1", "composition": "DESIGN", "itemNumber": {"id": "PN-1"}, "name": {"value": "Gear"},
                      "description": {"value": "A gear"}, "partNumber": {"value": "G-1"}})
        self.assertEqual(parse_summary(data), {"component_id": "c1", "composition": "DESIGN", "item_number": "PN-1",
                                               "part_number": "G-1", "name": "Gear", "description": "A gear"})

    def test_an_answer_of_an_unexpected_shape_is_empty(self):
        for data in ODD:
            with self.subTest(data=data):
                self.assertEqual(set(parse_summary(data).values()), {""})


class PropertiesTests(unittest.TestCase):
    def test_rows_are_sorted_by_name_and_nameless_ones_left_out(self):
        results = [{"name": "b", "displayValue": "2"}, {"name": "A", "displayValue": None}, {"displayValue": "x"}, None, "x"]
        data = model({"allProperties": {"results": results}})
        self.assertEqual(parse_properties(data), [{"name": "A", "value": ""}, {"name": "b", "value": "2"}])

    def test_an_answer_of_an_unexpected_shape_is_empty(self):
        for data in (*ODD, model({"allProperties": "x"}), model({"allProperties": {"results": "x"}})):
            with self.subTest(data=data):
                self.assertEqual(parse_properties(data), [])

    def test_a_component_answer(self):
        data = {"component": {"allProperties": {"results": [{"name": "Mass", "displayValue": "3 g"}]}}}
        self.assertEqual(parse_component(data), {"properties": [{"name": "Mass", "value": "3 g"}]})
        for odd in (None, "x", {"component": "x"}):
            with self.subTest(odd=odd):
                self.assertEqual(parse_component(odd), {"properties": []})


class StructureTests(unittest.TestCase):
    def test_rows_come_in_tree_order_with_their_level(self):
        rows = parse_structure([relation("a", "a2", 2), relation("root", "b", 2), relation("root", "a", 1), relation("a", "a1", 1)], "root")
        self.assertEqual([(row["id"], row["level"]) for row in rows], [("a", 0), ("a1", 1), ("a2", 1), ("b", 0)])

    def test_a_row_carries_its_details(self):
        child = {"hasChildren": True, "itemNumber": {"id": "PN-2"}, "name": {"value": "Bolt"}, "description": {"value": "M6"}}
        data = relation("root", "c", 7, **child)
        data["quantityProperty"] = {"displayValue": "4"}
        self.assertEqual(parse_structure([data], "root"), [{
            "level": 0, "id": "c", "has_children": True, "item_number": "PN-2", "sequence": 7, "name": "Bolt",
            "part_number": "PN-2", "description": "M6", "quantity": "4"}])   # no part number: the item number stands in

    def test_a_relation_that_is_not_one_is_skipped(self):
        self.assertEqual(parse_structure([None, "x", {"toComponent": "x"}, {"fromComponent": "x", "toComponent": {"id": "c"}}], "root"), [])

    def test_a_component_inside_itself_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_structure([relation("root", "a"), relation("a", "b"), relation("b", "a")], "root")


if __name__ == "__main__":
    unittest.main()

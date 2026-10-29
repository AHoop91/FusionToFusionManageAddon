"""Comparing Data Model properties with a Fusion Manage item. Run: python -m unittest discover tests"""

import unittest

from src.config.workspace_models import FieldMapping, data_model_name
from src.sync.property_compare import (FOUND, MATCH, MISMATCH, MULTIPLE, NEW, UNCHECKED, UNKNOWN, UNMAPPED,
                                        compare_properties)


class DataModelNameTests(unittest.TestCase):
    def test_built_in_uses_the_data_model_name_when_it_differs(self):
        self.assertEqual(data_model_name("material"), "materialName")

    def test_built_in_falls_back_to_the_label(self):
        self.assertEqual(data_model_name("revision"), "Revision")

    def test_hub_properties_use_the_stored_name(self):
        self.assertEqual(data_model_name("custom:Supplier"), "Supplier")
        self.assertEqual(data_model_name("base:partNumber"), "partNumber")

    def test_file_sources_have_no_property(self):
        self.assertEqual(data_model_name("thumbnail"), "")


class CompareTests(unittest.TestCase):
    mappings = [FieldMapping("part_number", "NUMBER"), FieldMapping("material", "MATERIAL")]
    properties = [{"name": "partNumber", "value": "PN-1"}, {"name": "materialName", "value": "Steel"},
                  {"name": "tipPartNumber", "value": "PN-1"}]
    summary = {"part_number": "PN-1", "description": ""}

    def rows(self, fm_fields, state):
        return {r["name"]: r for r in compare_properties(self.properties, self.summary, self.mappings, fm_fields, state)}

    def test_a_new_item_marks_mapped_rows_new_and_the_rest_unmapped(self):
        rows = self.rows(None, "new")
        self.assertEqual(rows["materialName"]["status"], NEW)
        self.assertEqual(rows["materialName"]["value"], "Steel")
        self.assertEqual(rows["tipPartNumber"]["status"], UNMAPPED)

    def test_a_found_item_compares_values(self):
        rows = self.rows({"NUMBER": "PN-1", "MATERIAL": "Brass"}, FOUND)
        self.assertEqual(rows["partNumber"]["status"], MATCH)
        self.assertEqual(rows["materialName"]["status"], MISMATCH)
        self.assertEqual(rows["materialName"]["fm_value"], "Brass")

    def test_a_value_fusion_lacks_never_replaces_one_fusion_manage_holds(self):
        properties = [{"name": "partNumber", "value": "PN-1"}, {"name": "materialName", "value": ""}]
        rows = {r["name"]: r for r in compare_properties(properties, self.summary, self.mappings,
                                                         {"NUMBER": "PN-1", "MATERIAL": "Steel"}, FOUND)}
        self.assertEqual(rows["materialName"]["status"], MATCH)

    def test_a_number_the_field_holds_at_its_precision_is_a_match(self):
        mappings = [FieldMapping("custom:Mass", "MASS")]
        properties = [{"name": "Mass", "value": "0.104455"}]
        to_three = lambda field, text: "0.104" if text == "0.104455" else text
        status = lambda fm, fit: compare_properties(properties, {}, mappings, {"MASS": fm}, FOUND, fit)[0]["status"]
        self.assertEqual(status("0.104", to_three), MATCH)
        self.assertEqual(status("0.105", to_three), MISMATCH)
        self.assertEqual(status("0.104", None), MISMATCH)

    def test_a_physical_rows_unit_and_original_value_come_through(self):
        mappings = [FieldMapping("physical:Mass", "MASS")]
        properties = [{"name": "Physical Mass", "value": "5.43342", "unit": "kg", "original": "5433.42 g"}]
        row = compare_properties(properties, {}, mappings, None, "new")[0]
        self.assertEqual((row["unit"], row["original"]), ("kg", "5433.42 g"))

    def test_property_names_match_without_case_or_spaces(self):
        mappings = [FieldMapping("custom:Material Name", "MATERIAL")]
        rows = compare_properties(self.properties, self.summary, mappings, None, "new")
        self.assertEqual([r["status"] for r in rows if r["name"] == "materialName"], [NEW])


class StateTests(unittest.TestCase):
    mappings = [FieldMapping("material", "MATERIAL")]
    properties = [{"name": "materialName", "value": "Steel"}]

    def status(self, state):
        return compare_properties(self.properties, {}, self.mappings, {"MATERIAL": "Steel"}, state)[0]["status"]

    def test_a_lookup_state_other_than_found_is_the_status_of_a_mapped_row(self):
        for state in (NEW, UNKNOWN, UNCHECKED, MULTIPLE):
            self.assertEqual(self.status(state), state)

    def test_a_state_that_is_not_one_of_them_is_refused_not_read_as_a_new_item(self):
        with self.assertRaises(ValueError):
            self.status("fond")


class UnlistedSourceTests(unittest.TestCase):
    def test_a_mapped_source_the_list_lacks_gets_a_row_from_the_summary(self):
        rows = compare_properties([], {"part_number": "PN-9"}, [FieldMapping("part_number", "NUMBER")], {"NUMBER": "PN-9"}, FOUND)
        self.assertEqual([(r["name"], r["value"], r["status"]) for r in rows], [("Part number", "PN-9", MATCH)])

    def test_a_built_in_in_the_summary_is_fresher_than_the_list(self):
        rows = compare_properties([{"name": "partNumber", "value": "OLD"}], {"part_number": "NEW"},
                                  [FieldMapping("part_number", "NUMBER")], {"NUMBER": "OLD"}, FOUND)
        self.assertEqual((rows[0]["value"], rows[0]["status"]), ("NEW", MISMATCH))


class OrderAndShownTests(unittest.TestCase):
    def test_rows_that_will_change_come_first_then_by_name(self):
        mappings = [FieldMapping("custom:B", "FB"), FieldMapping("custom:A", "FA"), FieldMapping("custom:C", "FC")]
        properties = [{"name": "Other", "value": "x"}, {"name": "C", "value": "1"}, {"name": "B", "value": "2"}, {"name": "A", "value": "1"}]
        rows = compare_properties(properties, {}, mappings, {"FA": "1", "FB": "9", "FC": "1"}, FOUND)
        self.assertEqual([(r["name"], r["status"]) for r in rows],
                         [("B", MISMATCH), ("A", MATCH), ("C", MATCH), ("Other", UNMAPPED)])

    def test_the_value_is_shown_at_the_precision_of_its_field(self):
        mappings = [FieldMapping("custom:Mass", "MASS")]
        rows = compare_properties([{"name": "Mass", "value": "0.104455"}], {}, mappings, None, NEW, lambda field, text: text[:5])
        self.assertEqual((rows[0]["value"], rows[0]["shown"]), ("0.104455", "0.104"))

    def test_a_unit_conversion_that_gives_nothing_leaves_the_value_as_it_is(self):
        mappings = [FieldMapping("physical:Mass", "MASS")]
        properties = [{"name": "Physical Mass", "value": "5", "unit": "kg"}]
        row = compare_properties(properties, {}, mappings, None, NEW, None, lambda field, number, unit: None)[0]
        self.assertEqual((row["value"], row["unit"]), ("5", "kg"))

    def test_a_converted_value_and_unit_replace_the_originals(self):
        mappings = [FieldMapping("physical:Mass", "MASS")]
        properties = [{"name": "Physical Mass", "value": "5", "unit": "kg"}]
        row = compare_properties(properties, {}, mappings, None, NEW, None, lambda field, number, unit: ("5000", "g"))[0]
        self.assertEqual((row["value"], row["unit"]), ("5000", "g"))


if __name__ == "__main__":
    unittest.main()

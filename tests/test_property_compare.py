"""Comparing Data Model properties with a Fusion Manage item. Run: python -m unittest discover tests"""

import unittest

from src.config.workspace_models import FieldMapping, data_model_name
from src.sync.property_compare import FOUND, MATCH, MISMATCH, NEW, UNMAPPED, compare_properties


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
    mappings = [FieldMapping("part_number", "NUMBER", True), FieldMapping("material", "MATERIAL")]
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

    def test_a_number_the_field_holds_at_its_precision_is_a_match(self):
        mappings = [FieldMapping("custom:Mass", "MASS")]
        properties = [{"name": "Mass", "value": "0.104455"}]
        to_three = lambda field, text: "0.104" if text == "0.104455" else text
        status = lambda fm, fit: compare_properties(properties, {}, mappings, {"MASS": fm}, FOUND, fit)[0]["status"]
        self.assertEqual(status("0.104", to_three), MATCH)
        self.assertEqual(status("0.105", to_three), MISMATCH)
        self.assertEqual(status("0.104", None), MISMATCH)

    def test_property_names_match_without_case_or_spaces(self):
        mappings = [FieldMapping("custom:Material Name", "MATERIAL")]
        rows = compare_properties(self.properties, self.summary, mappings, None, "new")
        self.assertEqual([r["status"] for r in rows if r["name"] == "materialName"], [NEW])


if __name__ == "__main__":
    unittest.main()

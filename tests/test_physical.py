import unittest

from src.config.workspace_models import data_model_name, is_valid_source
from src.fusion_mfg.physical import parse_physical
from src.fusion_mfg.properties import parse_definitions


def node(value, shown):
    return {"value": value, "displayValue": shown}


READY = {"component": {"primaryModel": {"physicalProperties": {"status": "COMPLETED", "mass": node(6.664223370078205, "6.66 kg"),
                                              "volume": node(848.9, "848.9 cm^3"), "area": node(819.4, "819.4 cm^2"), "density": node(0.00785, "0.00785"),
                                              "boundingBox": {"length": node(11.2966, "11.3 cm"), "height": node(36.5, "36.5 cm"), "width": node(21.4, "21.4 cm")}}}}}


class PhysicalTests(unittest.TestCase):
    def test_rows_are_plain_numbers_named_physical(self):
        rows = {r["name"]: r["value"] for r in parse_physical(READY)}
        self.assertEqual(rows["Physical Mass"], "6.66422")
        self.assertEqual(rows["Physical Length"], "11.2966")
        self.assertEqual(len(rows), 7)

    def test_mass_is_sent_in_kilograms(self):
        grams = {"component": {"primaryModel": {"physicalProperties": {"status": "COMPLETED",
                 "mass": {"value": 5433.42, "displayValue": "5433.42 g", "definition": {"units": {"name": "Grams"}}}}}}}
        self.assertEqual({r["name"]: r["value"] for r in parse_physical(grams)}["Physical Mass"], "5.43342")
        by_display = {"component": {"primaryModel": {"physicalProperties": {"status": "COMPLETED",
                      "mass": {"value": 2.0, "displayValue": "2 lbs"}}}}}
        self.assertEqual({r["name"]: r["value"] for r in parse_physical(by_display)}["Physical Mass"], "0.907185")

    def test_rows_carry_the_unit_and_the_original_value(self):
        data = {"component": {"primaryModel": {"physicalProperties": {"status": "COMPLETED",
                "mass": {"value": 5433.42, "displayValue": "5433.42", "definition": {"units": {"name": "Grams"}}},
                "volume": {"value": 692.156049, "displayValue": "692.156049", "definition": {"units": {"name": "Cubic centimeters"}}},
                "density": {"value": 0.00785, "displayValue": "0.00785", "definition": {"units": {"name": "Kilograms per Cubic Centimeter"}}}}}}}
        rows = {r["name"]: r for r in parse_physical(data)}
        self.assertEqual((rows["Physical Mass"]["unit"], rows["Physical Mass"]["original"]), ("kg", "5433.42 g"))
        self.assertEqual((rows["Physical Volume"]["unit"], rows["Physical Volume"]["original"]), ("cm³", "692.156049 cm³"))
        self.assertEqual(rows["Physical Density"]["unit"], "kg/cm³")
        self.assertEqual(rows["Physical Area"]["unit"], "")

    def test_every_mass_unit_is_converted_whether_named_in_the_singular_or_the_plural(self):
        for unit, value, kilograms in (("Kilograms", 2, "2"), ("kg", 2, "2"), ("Grams", 500, "0.5"), ("g", 500, "0.5"), ("Milligrams", 500, "0.0005"),
                                       ("Pounds", 1, "0.453592"), ("lbs", 1, "0.453592"), ("Ounces", 16, "0.453592"), ("oz", 16, "0.453592")):
            with self.subTest(unit=unit):
                data = {"component": {"primaryModel": {"physicalProperties": {"status": "COMPLETED",
                        "mass": {"value": value, "displayValue": str(value), "definition": {"units": {"name": unit}}}}}}}
                row = {r["name"]: r for r in parse_physical(data)}["Physical Mass"]
                self.assertEqual((row["value"], row["unit"]), (kilograms, "kg"))

    def test_a_mass_in_an_unknown_unit_is_sent_as_it_is(self):
        data = {"component": {"primaryModel": {"physicalProperties": {"status": "COMPLETED",
                "mass": {"value": 3.0, "displayValue": "3", "definition": {"units": {"name": "Stones"}}}}}}}
        row = {r["name"]: r for r in parse_physical(data)}["Physical Mass"]
        self.assertEqual((row["value"], row["unit"]), ("3", "stones"))   # unconverted, and its unit shown as the Data Model named it

    def test_an_answer_of_an_unexpected_shape_has_nothing(self):
        for data in ({}, {"component": "x"}, {"component": {"primaryModel": "x"}}, {"component": {"primaryModel": {"physicalProperties": "x"}}}):
            with self.subTest(data=data):
                self.assertEqual(parse_physical(data), [])

    def test_a_missing_or_odd_measurement_is_empty(self):
        data = {"component": {"primaryModel": {"physicalProperties": {"status": "COMPLETED", "mass": "x", "boundingBox": "x"}}}}
        rows = {r["name"]: r for r in parse_physical(data)}
        self.assertEqual({r["value"] for r in rows.values()}, {""})
        self.assertEqual(len(rows), 7)

    def test_nothing_until_calculated(self):
        pending = {"component": {"primaryModel": {"physicalProperties": {"status": "IN_PROGRESS"}}}}
        self.assertEqual(parse_physical(pending), [])
        self.assertEqual(parse_physical({"component": None}), [])

    def test_source_names_and_listing(self):
        self.assertTrue(is_valid_source("physical:Mass"))
        self.assertEqual(data_model_name("physical:Mass"), "Physical Mass")
        listed = [p for p in parse_definitions({"hub": {}}) if p["group"] == "physical"]
        self.assertEqual([p["name"] for p in listed], ["Mass", "Volume", "Area", "Density", "Length", "Width", "Height"])


if __name__ == "__main__":
    unittest.main()

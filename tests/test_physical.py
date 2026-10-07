import unittest

from src.config.workspace_models import data_model_name, is_valid_source, can_match
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

    def test_nothing_until_calculated(self):
        pending = {"component": {"primaryModel": {"physicalProperties": {"status": "IN_PROGRESS"}}}}
        self.assertEqual(parse_physical(pending), [])
        self.assertEqual(parse_physical({"component": None}), [])

    def test_source_names_and_listing(self):
        self.assertTrue(is_valid_source("physical:Mass"))
        self.assertEqual(data_model_name("physical:Mass"), "Physical Mass")
        self.assertFalse(can_match("physical:Mass"))
        listed = [p for p in parse_definitions({"hub": {}}) if p["group"] == "physical"]
        self.assertEqual([p["name"] for p in listed], ["Mass", "Volume", "Area", "Density", "Length", "Width", "Height"])


if __name__ == "__main__":
    unittest.main()

"""The Fusion Manage requests built from compared rows and BOM operations."""

import unittest

from src.config.workspace_models import StaticValue
from src.fm.sections import parse_sections
from src.publish.bom_requests import bom_requests
from src.publish.item_requests import item_request
from src.sync.property_compare import FOUND, MATCH, MISMATCH, NEW

SECTIONS = {"TITLE": "/api/v3/workspaces/1/sections/10", "TYPE": "/api/v3/workspaces/1/sections/10",
            "IMAGE": "/api/v3/workspaces/1/sections/11", "MATERIAL": "/api/v3/workspaces/1/sections/11"}
TYPE = StaticValue("TYPE", "/api/v3/lookups/TYPES/options/6")


def row(field, value, status):
    return {"name": field, "value": value, "fm_field": field, "fm_value": "", "status": status}


def entries(request):
    return {f["__self__"].rsplit("/", 1)[-1]: f["value"]
            for s in request["body"]["sections"] for f in s["fields"]}


class ItemRequestTests(unittest.TestCase):
    def test_new_item_is_posted_with_values_statics_and_images_but_not_blanks(self):
        rows = [row("TITLE", "Axle", NEW), row("MATERIAL", "", NEW)]
        request, reason = item_request("1", {"state": NEW}, rows, [TYPE], SECTIONS, [("IMAGE", "data:image/png;base64,AA")])
        self.assertEqual((request["method"], request["url"]), ("POST", "/api/v3/workspaces/1/items"))
        self.assertEqual(entries(request), {"TITLE": "Axle", "TYPE": {"link": TYPE.value}, "IMAGE": "data:image/png;base64,AA"})

    def test_existing_item_is_patched_with_differences_only(self):
        rows = [row("TITLE", "Axle", MISMATCH), row("MATERIAL", "Steel", MATCH)]
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, rows, [], SECTIONS)
        self.assertEqual((request["method"], request["url"]), ("PATCH", "/api/v3/workspaces/1/items/7"))
        self.assertEqual(entries(request), {"TITLE": "Axle"})

    def test_existing_item_with_nothing_to_send_makes_no_request(self):
        request, reason = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "A", MATCH)], [], SECTIONS)
        self.assertIsNone(request)
        self.assertTrue(reason)

    def test_values_are_grouped_by_section(self):
        rows = [row("TITLE", "Axle", NEW), row("MATERIAL", "Steel", NEW)]
        request, _ = item_request("1", {"state": NEW}, rows, [], SECTIONS)
        links = sorted(s["link"] for s in request["body"]["sections"])
        self.assertEqual(links, ["/api/v3/workspaces/1/sections/10", "/api/v3/workspaces/1/sections/11"])

    def test_a_field_in_no_section_explains_itself(self):
        request, reason = item_request("1", {"state": NEW}, [row("NOPE", "x", NEW)], [], SECTIONS)
        self.assertIsNone(request)
        self.assertIn("NOPE", reason)


class SectionTests(unittest.TestCase):
    def test_fields_and_matrix_fields_map_to_their_section(self):
        data = [{"__self__": "/api/v3/workspaces/1/sections/10",
                 "fields": [{"link": "/api/v3/workspaces/1/views/1/fields/TITLE"}],
                 "matrices": [{"fields": [[{"link": "/api/v3/workspaces/1/views/1/fields/COST"}]]}]}]
        self.assertEqual(parse_sections(data), {"TITLE": "/api/v3/workspaces/1/sections/10",
                                                "COST": "/api/v3/workspaces/1/sections/10"})


class BomRequestTests(unittest.TestCase):
    def test_a_line_is_freed_before_another_takes_its_number(self):
        ops = [{"op": "add", "parent": "A", "number": "C", "quantity": 1, "sequence": 2},
               {"op": "remove", "parent": "A", "number": "B", "sequence": 2}]
        methods = [r["method"] for r in bom_requests("1", ops)["A"]]
        self.assertEqual(methods, ["DELETE", "POST"])


if __name__ == "__main__":
    unittest.main()

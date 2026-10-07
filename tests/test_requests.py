"""The Fusion Manage requests built from compared rows and BOM operations."""

import unittest

from src.config.workspace_models import StaticValue
from src.fm.components import _matches
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

    def test_component_link_is_sent_on_create_and_added_to_an_item_that_lacks_it(self):
        link = "/api/v3/workspaces/57/items/15695"
        sections = {**SECTIONS, "COMPONENT": "/api/v3/workspaces/1/sections/10"}
        created, _ = item_request("1", {"state": NEW}, [row("TITLE", "Axle", NEW)], [], sections, None, None, ("COMPONENT", link))
        self.assertEqual(entries(created)["COMPONENT"], {"link": link})
        lacking, _ = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "Axle", MATCH)], [], sections, None, {}, ("COMPONENT", link))
        self.assertEqual(entries(lacking), {"COMPONENT": {"link": link}})
        holding, reason = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "Axle", MATCH)], [], sections, None,
                                       {"COMPONENT": {"link": link, "title": "PN-1"}}, ("COMPONENT", link))
        self.assertIsNone(holding)

    def test_component_option_matches_the_number_not_a_longer_one(self):
        self.assertTrue(_matches("PN-000703", "pn-000703"))
        self.assertTrue(_matches("PN-000703 - Axle", "PN-000703"))
        self.assertFalse(_matches("PN-0007031", "PN-000703"))

    def test_existing_item_is_patched_with_differences_only(self):
        rows = [row("TITLE", "Axle", MISMATCH), row("MATERIAL", "Steel", MATCH)]
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, rows, [], SECTIONS)
        self.assertEqual((request["method"], request["url"]), ("PATCH", "/api/v3/workspaces/1/items/7"))
        self.assertEqual(entries(request), {"TITLE": "Axle"})

    def test_an_update_names_the_sections_and_fields_of_the_item_itself(self):
        rows = [row("TITLE", "Axle", MISMATCH)]
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, rows, [], SECTIONS)
        section = request["body"]["sections"][0]
        self.assertEqual(section["link"], "/api/v3/workspaces/1/items/7/views/1/sections/10")
        self.assertEqual(section["fields"][0]["__self__"], "/api/v3/workspaces/1/items/7/views/1/fields/TITLE")

    def test_a_static_value_the_item_already_holds_does_not_make_an_update(self):
        held = {"TYPE": {"link": TYPE.value, "title": "Part"}}
        request, reason = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "A", MATCH)], [TYPE], SECTIONS,
                                       [("IMAGE", "data:image/png;base64,AA")], held)
        self.assertIsNone(request)
        self.assertTrue(reason)

    def test_a_static_value_the_item_lacks_makes_an_update(self):
        held = {"TYPE": {"link": "/api/v3/lookups/TYPES/options/2"}}
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "A", MATCH)], [TYPE], SECTIONS,
                                  [("IMAGE", "data:image/png;base64,AA")], held)
        self.assertEqual(set(entries(request)), {"TYPE", "IMAGE"})   # the image goes along; the unchanged title does not

    def test_a_new_static_value_is_sent_to_an_item_that_has_no_value_for_it(self):
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "A", MATCH)], [TYPE], SECTIONS, [], {})
        self.assertEqual(set(entries(request)), {"TYPE"})

    def test_a_static_text_value_is_compared_as_text(self):
        text = StaticValue("TITLE", "Axle")
        none, _ = item_request("1", {"state": FOUND, "item_id": "7"}, [], [text], SECTIONS, [], {"TITLE": "Axle"})
        self.assertIsNone(none)

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

    def test_remove_deletes_the_line_by_its_id(self):
        request = bom_requests("57", [{"op": "remove", "parent": "A", "number": "B", "sequence": 2, "edge": "13836"}])["A"][0]
        self.assertEqual((request["method"], request["body"]), ("DELETE", None))
        self.assertTrue(request["url"].endswith("/workspaces/57/items/{{item:A}}/bom-items/13836"))

    def test_add_posts_the_linkable_row_with_its_line_number(self):
        row = {"__self__": "/api/v3/workspaces/57/items/14669/views/5/linkable-items/15719", "urn": "urn:x",
               "item": {"link": "/api/v3/workspaces/57/items/15719", "title": "WG1-6073 - HEX NUT"}}
        request = bom_requests("57", [{"op": "add", "parent": "A", "number": "WG1-6073", "sequence": "1", "quantity": 2, "linkable": row}])["A"][0]
        self.assertEqual(request["body"], {**row, "itemNumber": 1, "quantity": "2", "children": [], "fields": []})

    def test_add_without_a_linkable_row_links_the_item_by_placeholder(self):
        body = bom_requests("57", [{"op": "add", "parent": "A", "number": "C", "sequence": "2"}])["A"][0]["body"]
        self.assertEqual(body["item"]["link"], "/api/v3/workspaces/57/items/{{item:C}}")
        self.assertEqual(body["__self__"], "/api/v3/workspaces/57/items/{{item:A}}/views/5/linkable-items/{{item:C}}")
        self.assertEqual(body["urn"], "urn:adsk.plm:tenant.workspace.item.view.linkable-item:{{tenant}}.57.{{item:A}}.5.{{item:C}}")
        self.assertEqual(list(body), ["__self__", "urn", "item", "itemNumber", "quantity", "children", "fields"])


if __name__ == "__main__":
    unittest.main()

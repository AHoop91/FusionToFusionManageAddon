"""The Fusion Manage requests built from compared rows and BOM operations."""

import unittest

from src.config.workspace_models import StaticValue
from src.fm.components import _matches
from src.fm.sections import parse_sections
from src.publish.bom_requests import bom_requests
from src.publish.item_requests import field_entry, item_request
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

    def test_an_update_never_blanks_a_field(self):
        rows = [row("TITLE", "Axle", MISMATCH), row("MATERIAL", "", MISMATCH)]
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, rows, [], SECTIONS)
        self.assertEqual(entries(request), {"TITLE": "Axle"})

    def test_an_update_names_the_sections_and_fields_of_the_item_itself(self):
        rows = [row("TITLE", "Axle", MISMATCH)]
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, rows, [], SECTIONS)
        section = request["body"]["sections"][0]
        self.assertEqual(section["link"], "/api/v3/workspaces/1/items/7/views/1/sections/10")
        self.assertEqual(section["fields"][0]["__self__"], "/api/v3/workspaces/1/items/7/views/1/fields/TITLE")

    def test_a_static_value_the_item_already_holds_does_not_make_an_update(self):
        held = {"TYPE": {"link": TYPE.value, "title": "Part"}}
        request, reason = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "A", MATCH)], [TYPE], SECTIONS, [], held)
        self.assertIsNone(request)
        self.assertTrue(reason)

    def test_an_image_makes_an_update_on_its_own_since_it_cannot_be_compared(self):
        held = {"TYPE": {"link": TYPE.value, "title": "Part"}}
        request, reason = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "A", MATCH)], [TYPE], SECTIONS,
                                       [("IMAGE", "data:image/png;base64,AA")], held)
        self.assertEqual((request["method"], request["url"]), ("PATCH", "/api/v3/workspaces/1/items/7"))
        self.assertEqual(entries(request), {"IMAGE": "data:image/png;base64,AA"})   # nothing else differs: only the image goes
        self.assertEqual(reason, "")

    def test_an_image_goes_along_with_an_update_that_has_other_differences(self):
        request, _ = item_request("1", {"state": FOUND, "item_id": "7"}, [row("TITLE", "Axle", MISMATCH)], [], SECTIONS,
                                  [("IMAGE", "data:image/png;base64,AA")], {})
        self.assertEqual(entries(request), {"TITLE": "Axle", "IMAGE": "data:image/png;base64,AA"})

    def test_an_item_that_is_not_found_or_new_gets_no_image_request(self):
        request, reason = item_request("1", {"state": "error", "message": "No access"}, [], [], SECTIONS, [("IMAGE", "data:image/png;base64,AA")])
        self.assertEqual((request, reason), (None, "No access"))

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

    def test_a_blank_or_missing_mapped_value_is_never_sent_but_zero_is(self):
        rows = [row("TITLE", None, NEW), row("MATERIAL", "   ", NEW), row("COST", 0, NEW)]
        request, _ = item_request("1", {"state": NEW}, rows, [], {**SECTIONS, "COST": SECTIONS["TITLE"]})
        self.assertEqual(entries(request), {"COST": 0})

    def test_an_item_found_without_an_id_cannot_be_updated(self):
        for fm in ({"state": FOUND}, {"state": FOUND, "item_id": ""}, {"state": FOUND, "item_id": None}):
            with self.subTest(fm=fm):
                request, reason = item_request("1", fm, [row("TITLE", "Axle", MISMATCH)], [], SECTIONS)
                self.assertIsNone(request)
                self.assertIn("did not give its id", reason)

    def test_a_state_that_is_neither_new_nor_found_gives_its_message_or_names_itself(self):
        self.assertEqual(item_request("1", {"state": "ERROR", "message": "No access"}, [], [], SECTIONS), (None, "No access"))
        self.assertEqual(item_request("1", {"state": "ERROR"}, [], [], SECTIONS), (None, "Fusion Manage state is ERROR."))

    def test_a_picklist_option_is_sent_as_a_link_and_other_text_as_it_is(self):
        self.assertEqual(field_entry("/w/1", "TYPE", TYPE.value)["value"], {"link": TYPE.value})
        self.assertEqual(field_entry("/w/1", "TITLE", "/api/v3/other")["value"], "/api/v3/other")
        self.assertEqual(field_entry("/w/1", "TITLE", "Axle")["__self__"], "/w/1/views/1/fields/TITLE")

    def test_a_new_item_names_the_workspaces_sections(self):
        request, _ = item_request("1", {"state": NEW}, [row("TITLE", "Axle", NEW)], [], SECTIONS)
        self.assertEqual(request["body"]["sections"][0]["link"], SECTIONS["TITLE"])

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
        self.assertEqual(list(body), ["__self__", "urn", "item", "itemNumber", "children", "fields"])   # no quantity was given: none is sent

    def test_a_changed_line_is_sent_as_the_bom_tab_sends_it(self):
        request = bom_requests("242", [{"op": "update", "parent": "A", "number": "B", "quantity": 2, "sequence": "1", "edge": "5284"}])["A"][0]
        url = "/api/v3/workspaces/242/items/{{item:A}}/bom-items/5284"
        self.assertEqual((request["method"], request["url"]), ("PATCH", url))
        body = request["body"]
        self.assertEqual((body["__self__"], body["quantity"], body["children"], body["fields"]), (url, "2", [], []))
        self.assertEqual(body["item"]["link"], "/api/v3/workspaces/242/items/{{item:B}}")
        self.assertEqual(body["item"]["version"], "{{version:B}}")

    def test_a_line_whose_id_is_not_known_is_named_by_a_marker_of_where_it_was(self):
        update = bom_requests("242", [{"op": "update", "parent": "A", "number": "B", "quantity": 2, "sequence": "1"}])["A"][0]
        renumber = bom_requests("242", [{"op": "renumber", "parent": "A", "number": "B", "sequence": "3", "from_sequence": "1"}])["A"][0]
        self.assertTrue(update["url"].endswith("/bom-items/{{edge:A>B@1}}"))
        self.assertTrue(renumber["url"].endswith("/bom-items/{{edge:A>B@1}}"))   # by the number it has now, not the one it is given

    def test_an_item_picked_in_fusion_manage_keeps_its_link(self):
        body = bom_requests("57", [{"op": "add", "parent": "A", "number": "C", "sequence": "2", "link": "/api/v3/workspaces/57/items/77"}])["A"][0]["body"]
        self.assertEqual(body["item"]["link"], "/api/v3/workspaces/57/items/77")
        self.assertEqual((body["item"]["title"], body["item"]["version"]), ("C", "{{version:C}}"))

    def test_a_renumber_that_has_a_quantity_keeps_it(self):
        body = bom_requests("242", [{"op": "renumber", "parent": "A", "number": "B", "sequence": "3", "quantity": 4, "edge": "9"}])["A"][0]["body"]
        self.assertEqual(body["quantity"], "4")

    def test_a_number_that_is_not_plain_digits_is_sent_as_it_is(self):
        body = bom_requests("242", [{"op": "renumber", "parent": "A", "number": "B", "sequence": "\u00b2", "from_sequence": "1", "edge": "9"}])["A"][0]["body"]
        self.assertEqual(body["itemNumber"], "\u00b2")
        padded = bom_requests("242", [{"op": "renumber", "parent": "A", "number": "B", "sequence": " 12 ", "edge": "9"}])["A"][0]["body"]
        self.assertEqual(padded["itemNumber"], 12)

    def test_a_blank_quantity_is_never_sent(self):
        for blank in ("", "  ", None):
            with self.subTest(quantity=blank):
                add = bom_requests("57", [{"op": "add", "parent": "A", "number": "C", "sequence": "2", "quantity": blank}])["A"][0]["body"]
                renumber = bom_requests("57", [{"op": "renumber", "parent": "A", "number": "B", "sequence": "3", "quantity": blank, "edge": "9"}])["A"][0]["body"]
                self.assertNotIn("quantity", add)
                self.assertNotIn("quantity", renumber)
                self.assertEqual(bom_requests("57", [{"op": "update", "parent": "A", "number": "B", "quantity": blank, "edge": "9"}]), {})

    def test_a_quantity_of_zero_is_sent(self):
        body = bom_requests("57", [{"op": "update", "parent": "A", "number": "B", "quantity": 0, "edge": "9"}])["A"][0]["body"]
        self.assertEqual(body["quantity"], "0")

    def test_an_operation_of_another_kind_makes_no_request(self):
        self.assertEqual(bom_requests("1", [{"op": "frobnicate", "parent": "A", "number": "B"}]), {})

    def test_a_renumbered_line_carries_its_new_number(self):
        body = bom_requests("242", [{"op": "renumber", "parent": "A", "number": "B", "sequence": "3", "from_sequence": "1", "edge": "9"}])["A"][0]["body"]
        self.assertEqual(body["itemNumber"], 3)
        self.assertNotIn("quantity", body)


if __name__ == "__main__":
    unittest.main()

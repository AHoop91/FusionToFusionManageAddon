"""An item laid out for the Item tab: how a field becomes a cell, which fields are shown, and how matrices and sections are built."""

import unittest
from unittest import mock

from src.fm.client import FmApiError
from src.fm.item_view import ItemViewService, build_view, cell_of, no_image, no_page, not_shown
from src.fm.sections import SectionService
from src.fm.tabs import TabService

FIELD = "/api/v3/workspaces/1/views/1/fields/"


def ref(fid):
    return {"link": FIELD + fid}


def field(fid, value=None, kind="", **extra):
    return {"__self__": FIELD + fid, "title": fid.title(), "value": value, "type": {"title": kind}, **extra}


def section(title, *fields, link="/api/v3/workspaces/1/sections/10"):
    return {"title": title, "link": link, "fields": list(fields)}


def view(item, layouts=None, hidden=None):
    return build_view(item, layouts or {}, no_image, "https://acme.autodeskplm360.net", hidden)


class StateTests(unittest.TestCase):
    def test_the_workflow_state_of_an_item_is_in_the_view(self):
        item = {"title": "24-000002 - Universal Joint", "currentState": {"title": "Proposal"}, "sections": [section("Basic", field("NUMBER", "24-000002"))]}
        self.assertEqual(view(item)["state"], "Proposal")

    def test_an_item_with_no_workflow_state_has_a_blank_one(self):
        self.assertEqual(view({"title": "x", "sections": [section("Basic", field("NUMBER", "1"))]})["state"], "")


class CellTests(unittest.TestCase):
    def cell(self, node, images=no_image, pages=no_page):
        return cell_of(node, images, pages)

    def test_plain_text_with_its_unit_of_measure(self):
        cell = self.cell(field("MASS", "12", uom="kg"))
        self.assertEqual((cell["id"], cell["kind"], cell["value"]), ("MASS", "text", "12 kg"))

    def test_a_check_box_reads_yes_or_no(self):
        self.assertEqual(self.cell(field("OK", "true", "Check Box"))["value"], "Yes")
        self.assertEqual(self.cell(field("OK", "false", "Check Box"))["value"], "No")

    def test_no_value_has_no_unit_either(self):
        self.assertEqual(self.cell(field("MASS", None, uom="kg"))["value"], "")

    def test_escaped_markup_is_html(self):
        cell = self.cell(field("F", "&lt;b&gt;bold&lt;/b&gt;"))
        self.assertEqual((cell["kind"], cell["value"]), ("html", "<b>bold</b>"))

    def test_an_image_is_loaded_by_its_link(self):
        cell = self.cell(field("PIC", {"link": "/img/1"}, "Image"), images=lambda link: f"data:{link}")
        self.assertEqual((cell["kind"], cell["value"]), ("image", "data:/img/1"))
        self.assertEqual(self.cell(field("PIC", "oops", "Image"))["value"], "")

    def test_links_to_items_that_have_pages_are_links(self):
        value = [{"link": "/api/v3/workspaces/1/items/5", "title": "A"}, {"link": "/api/v3/workspaces/1/items/6", "title": "B"}]
        cell = self.cell(field("REL", value), pages=lambda link: "https://page" + link)
        self.assertEqual(cell["kind"], "links")
        self.assertEqual([c["title"] for c in cell["value"]], ["A", "B"])

    def test_links_where_one_has_no_page_are_text(self):
        value = [{"link": "/x/1", "title": "A"}, {"link": "/x/2", "title": "B"}]
        cell = self.cell(field("REL", value), pages=lambda link: "page" if link == "/x/1" else "")
        self.assertEqual((cell["kind"], cell["value"]), ("text", "A, B"))


class NotShownTests(unittest.TestCase):
    def test_hidden_and_create_only_fields_are_not_shown(self):
        for node in ({"visibility": "NEVER"}, {"visibility": "hidden"}, {"visibility": "CREATE_ONLY"}, {"visible": False}, {"hidden": True}):
            with self.subTest(node=node):
                self.assertTrue(not_shown(node, set()))

    def test_a_field_the_workspace_hides_is_not_shown(self):
        self.assertTrue(not_shown(field("SECRET"), {"SECRET"}))

    def test_visible_fields_and_anything_not_a_field_are_shown(self):
        for node in ({"visibility": "ALWAYS"}, {}, None, "x"):
            with self.subTest(node=node):
                self.assertFalse(not_shown(node, set()))


class BuildViewTests(unittest.TestCase):
    def test_the_header_gives_the_state_the_life_cycle_and_the_type(self):
        item = {"title": "PN-1 - Axle", "versionId": "w", "lifecycle": {"title": "Design"}, "workspace": {"title": "Items"},
                "sections": [section("Details", field("TYPE", "Part", "Single Selection"), field("NOTE", "x"))]}
        built = view(item)
        self.assertEqual((built["title"], built["workspace"], built["header"]), ("PN-1 - Axle", "Items", ["Pending", "Design", "Part"]))

    def test_the_type_is_in_the_header_even_when_it_is_hidden_from_the_fields(self):
        item = {"sections": [section("Details", field("TYPE", "Part"), field("NOTE", "x"))]}
        built = view(item, hidden={"TYPE"})
        self.assertEqual(built["header"], ["Part"])
        self.assertEqual([f["id"] for f in built["sections"][0]["fields"]], ["NOTE"])

    def test_a_section_with_nothing_shown_is_left_out(self):
        item = {"sections": [section("Empty", field("A", "x")), section("Full", field("B", "y"))]}
        built = view(item, hidden={"A"})
        self.assertEqual([s["title"] for s in built["sections"]], ["Full"])

    def test_a_field_in_a_matrix_is_shown_there_and_not_again(self):
        layout = {"10": {"matrices": [{"fields": [[ref("A"), ref("B")]], "columns": ["Left", "Right"]}]}}
        item = {"sections": [section("Details", field("A", "1"), field("B", "2"), field("C", "3"))]}
        (found,) = view(item, layout)["sections"]
        self.assertEqual([f["id"] for f in found["fields"]], ["C"])
        (matrix,) = found["matrices"]
        self.assertEqual(matrix["columns"], ["Left", "Right"])
        self.assertEqual([[c["value"] for c in row] for row in matrix["rows"]], [["1", "2"]])

    def test_a_picture_in_a_matrix_keeps_its_link_for_a_page_that_loads_it_later(self):
        layout = {"10": {"matrices": [{"fields": [[ref("PIC"), ref("A")]], "columns": ["Picture", "Text"]}]}}
        item = {"sections": [section("Details", field("PIC", {"link": "/img/1"}, "Image"), field("A", "1"))]}
        (matrix,) = view(item, layout)["sections"][0]["matrices"]
        picture, text = matrix["rows"][0]
        self.assertEqual((picture["kind"], picture["link"], picture["value"]), ("image", "/img/1", ""))
        self.assertNotIn("link", text)

    def test_a_section_the_workspace_lays_out_folded_is_marked_collapsed(self):
        layout = {"10": {"collapsed": True}, "11": {"collapsed": False}}
        item = {"sections": [section("Folded", field("A", "1")), section("Open", field("B", "2"), link="/api/v3/workspaces/1/sections/11"),
                             section("Unlisted", field("C", "3"), link="/api/v3/workspaces/1/sections/12")]}
        self.assertEqual([s["collapsed"] for s in view(item, layout)["sections"]], [True, False, False])

    def test_a_matrix_column_that_is_all_hidden_is_left_out_with_its_name(self):
        layout = {"10": {"matrices": [{"fields": [[ref("A"), ref("B")], [ref("C"), ref("D")]], "columns": ["One", "Two"], "rows": ["x", "y"]}]}}
        item = {"sections": [section("Details", *(field(f, f) for f in "ABCD"))]}
        (matrix,) = view(item, layout, hidden={"B", "D"})["sections"][0]["matrices"]
        self.assertEqual(matrix["columns"], ["One"])
        self.assertEqual(matrix["labels"], ["x", "y"])
        self.assertEqual([[c["value"] for c in row] for row in matrix["rows"]], [["A"], ["C"]])

    def test_columns_the_layout_does_not_name_are_titled_by_the_first_row(self):
        layout = {"10": {"matrices": [{"fields": [[ref("A"), ref("B")]]}]}}
        item = {"sections": [section("Details", field("A", "1"), field("B", "2"))]}
        (matrix,) = view(item, layout)["sections"][0]["matrices"]
        self.assertEqual((matrix["columns"], matrix["labels"]), (["A", "B"], [""]))

    def test_rubbish_gives_an_empty_view(self):
        for item in (None, "x", [], {"sections": "x"}, {"sections": ["x", {"fields": "x"}]}):
            with self.subTest(item=item):
                self.assertEqual(view(item)["sections"], [])


class ServiceTests(unittest.TestCase):
    """``ItemViewService.layout`` and ``read`` over a client that answers by address and keeps the addresses it was asked."""

    def setUp(self):
        ItemViewService.forget()
        self.addCleanup(ItemViewService.forget)
        self.asked = []
        self.item = {"title": "PN-1", "urn": "urn:adsk.plm:tenant.workspace.item:ACME.57.1", "sections": [section("Basic", field("NUMBER", "PN-1"))]}
        self.client = mock.Mock(tenant="acme", base_url="https://acme.autodeskplm360.net")
        self.client.get_json.side_effect = self.answer

    def answer(self, path, *_args):
        self.asked.append(path)
        return self.item if path.endswith("/items/I1") else {}

    def test_layout_reads_the_item_once_and_no_tabs_or_permissions(self):
        view = ItemViewService(self.client).layout("57", "I1", pictures=False)
        self.assertEqual(self.asked.count("/api/v3/workspaces/57/items/I1"), 1)
        self.assertFalse([path for path in self.asked if path.endswith("/tabs") or "permission" in path])
        self.assertNotIn("tabs", view)
        self.assertEqual((view["title"], view["item_id"], view["workspace_id"], view["item_urn"]),
                         ("PN-1", "I1", "57", "urn:adsk.plm:tenant.workspace.item:ACME.57.1"))
        self.assertEqual([f["value"] for f in view["sections"][0]["fields"]], ["PN-1"])

    def test_read_is_the_layout_with_the_tabs(self):
        tabs = {"files": {"label": "Attachments", "count": 2, "allowed": True}}
        with mock.patch.object(TabService, "read", return_value=tabs) as read:
            whole = ItemViewService(self.client).read("57", "I1", {"VIEW"}, with_grid=True, pictures=False)
        read.assert_called_once_with("57", "I1", {"VIEW"}, True)
        self.assertEqual(whole, {**ItemViewService(self.client).layout("57", "I1", pictures=False), "tabs": tabs})

    def test_an_answer_that_is_not_an_item_is_an_error(self):
        self.item = []
        with mock.patch.object(TabService, "read", return_value={}):
            for read in (lambda: ItemViewService(self.client).layout("57", "I1"), lambda: ItemViewService(self.client).read("57", "I1", set())):
                with self.assertRaises(FmApiError) as raised:
                    read()
                self.assertIn("gave no item I1", str(raised.exception))

    def test_a_failing_item_read_is_an_error(self):
        def answer(path, *_args):
            if path.endswith("/items/I1"):
                raise FmApiError("down")
            return {}
        self.client.get_json.side_effect = answer
        with mock.patch.object(TabService, "read", return_value={}), self.assertRaises(FmApiError):
            ItemViewService(self.client).read("57", "I1", set())


class ForgetTests(unittest.TestCase):
    def test_forget_drops_the_layout_kept_of_a_workspace(self):
        key = ("acme", "1")
        kept = (SectionService._cache, SectionService._details_cache, TabService._labels_cache, ItemViewService._hidden_cache)
        for cache in kept:
            cache.put(key, {"kept": True})
        ItemViewService.forget()
        for cache in kept:
            self.assertIsNone(cache.get(key))


if __name__ == "__main__":
    unittest.main()

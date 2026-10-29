"""An item laid out for the Item tab: how a field becomes a cell, which fields are shown, and how matrices and sections are built."""

import unittest

from src.fm.item_view import build_view, cell_of, no_image, no_page, not_shown

FIELD = "/api/v3/workspaces/1/views/1/fields/"


def ref(fid):
    return {"link": FIELD + fid}


def field(fid, value=None, kind="", **extra):
    return {"__self__": FIELD + fid, "title": fid.title(), "value": value, "type": {"title": kind}, **extra}


def section(title, *fields, link="/api/v3/workspaces/1/sections/10"):
    return {"title": title, "link": link, "fields": list(fields)}


def view(item, layouts=None, hidden=None):
    return build_view(item, layouts or {}, no_image, "https://acme.autodeskplm360.net", hidden)


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


if __name__ == "__main__":
    unittest.main()

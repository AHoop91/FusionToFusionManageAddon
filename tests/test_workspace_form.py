import unittest

from src.fm.workspace_form import WorkspaceFormService, parse_form


def _field(field_id, type_title="Single Line Text", **more):
    return {"__self__": f"/api/v3/workspaces/77/fields/{field_id}", "name": field_id.title(), "type": {"title": type_title}, **more}


def _section(title, *ids):
    return {"__self__": "/api/v3/workspaces/77/sections/1", "title": title,
            "fields": [{"__self__": f"/api/v3/workspaces/77/views/1/fields/{i}"} for i in ids]}


OPTIONS = {"STATES": [{"value": "/api/v3/lookups/STATES/options/1", "title": "Proposal"}]}


class ParseFormTests(unittest.TestCase):
    def test_each_section_lists_its_fields_with_the_control_their_type_needs(self):
        rows = [_field("TITLE"), _field("NOTES", "Paragraph"), _field("COUNT", "Integer"), _field("COST", "Float"), _field("DUE", "Date"),
                _field("ACTIVE", "Check Box"), _field("STATE", "Single Selection", picklist="/api/v3/lookups/STATES")]
        form = parse_form(rows, [_section("Basic", "TITLE", "NOTES", "COUNT"), _section("More", "COST", "DUE", "ACTIVE", "STATE")], OPTIONS)
        self.assertEqual([s["title"] for s in form["sections"]], ["Basic", "More"])
        kinds = {f["id"]: f["kind"] for s in form["sections"] for f in s["fields"]}
        self.assertEqual(kinds, {"TITLE": "text", "NOTES": "textarea", "COUNT": "integer", "COST": "number", "DUE": "date", "ACTIVE": "checkbox",
                                 "STATE": "select"})
        state = form["sections"][1]["fields"][3]
        self.assertEqual(state["options"], OPTIONS["STATES"])

    def test_a_field_the_add_in_fills_in_has_nothing_to_enter_and_says_so(self):
        rows = [_field("TITLE"), _field("PRIMARY", "Single Selection", picklist="/api/v3/lookups/STATES", editability="ALWAYS", fieldValidators=[{"validatorName": "required"}])]
        form = parse_form(rows, [_section("S", "TITLE", "PRIMARY")], OPTIONS, {"PRIMARY"})
        title, primary = form["sections"][0]["fields"]
        self.assertEqual(title["kind"], "text")
        self.assertEqual((primary["kind"], primary["required"], primary["options"]), ("auto", False, []))
        self.assertIn("automatically", primary["description"])

    def test_a_section_says_whether_it_starts_folded(self):
        folded = dict(_section("More", "B"), collapsed=True)
        form = parse_form([_field("A"), _field("B"), _field("C")], [dict(_section("Basic", "A"), collapsed=False), folded, _section("Plain", "C")], {})
        self.assertEqual([s["collapsed"] for s in form["sections"]], [False, True, False])

    def test_the_fields_keep_the_order_of_the_section(self):
        form = parse_form([_field("A"), _field("B"), _field("C")], [_section("S", "C", "A", "B")], {})
        self.assertEqual([f["id"] for f in form["sections"][0]["fields"]], ["C", "A", "B"])

    def test_a_field_nobody_can_fill_in_is_left_out(self):
        rows = [_field("OK"), _field("FIXED", editability="NEVER"), _field("SUM", formulaField=True), _field("HIDDEN", visibility="NEVER")]
        form = parse_form(rows, [_section("S", "OK", "FIXED", "SUM", "HIDDEN")], {})
        self.assertEqual([f["id"] for f in form["sections"][0]["fields"]], ["OK"])

    def test_a_field_with_no_control_is_left_out_and_reported(self):
        form = parse_form([_field("OK"), _field("PIC", "Flyout")], [_section("S", "OK", "PIC")], {})
        self.assertEqual(([f["id"] for f in form["sections"][0]["fields"]], form["left_out"]), (["OK"], ["PIC"]))

    def test_a_link_to_items_of_another_workspace_is_searched_by_its_lookup_not_listed(self):
        rows = [_field("OWNER", "Pick List", picklist="/api/v3/lookups/WS_9", picklistFieldDefinition={"x": 1}),
                _field("TEAM", "Multiple Selection", picklist="/api/v3/lookups/WS_9", picklistFieldDefinition={"x": 1})]
        fields = parse_form(rows, [_section("S", "OWNER", "TEAM")], OPTIONS)["sections"][0]["fields"]
        self.assertEqual([(f["kind"], f["lookup"], f["options"]) for f in fields], [("link", "WS_9", []), ("links", "WS_9", [])])

    def test_an_image_field_gets_an_image_control(self):
        form = parse_form([_field("PIC", "Image")], [_section("S", "PIC")], {})
        self.assertEqual(form["sections"][0]["fields"][0]["kind"], "image")

    def test_a_radio_button_field_gets_radio_buttons_and_a_selection_field_a_list(self):
        rows = [_field("YEAR", "Radio Button", picklist="/api/v3/lookups/STATES"), _field("STATE", "Single Selection", picklist="/api/v3/lookups/STATES")]
        kinds = [f["kind"] for f in parse_form(rows, [_section("S", "YEAR", "STATE")], OPTIONS)["sections"][0]["fields"]]
        self.assertEqual(kinds, ["radio", "select"])

    def test_a_field_nobody_can_edit_is_shown_as_what_it_says_about_itself(self):
        rows = [_field("NUMBER", editability="NEVER", description="The item number will automatically be assigned"), _field("OK")]
        fields = parse_form(rows, [_section("S", "NUMBER", "OK")], {})["sections"][0]["fields"]
        self.assertEqual([(f["id"], f["kind"], f["description"]) for f in fields],
                         [("NUMBER", "info", "The item number will automatically be assigned"), ("OK", "text", "")])

    def test_a_text_field_has_the_limit_its_validator_or_its_length_gives_and_the_smaller_wins(self):
        rows = [_field("TITLE", fieldLength=200, fieldValidators=[{"validatorName": "required"}]),
                _field("NOTES", "Paragraph", fieldLength=None, fieldValidators=[{"validatorName": "maxlength", "variables": {"maxlength": "10000"}}]),
                _field("CODE", fieldLength=50, fieldValidators=[{"validatorName": "maxlength", "variables": {"maxlength": "20"}}]),
                _field("FREE")]
        fields = parse_form(rows, [_section("S", "TITLE", "NOTES", "CODE", "FREE")], {})["sections"][0]["fields"]
        self.assertEqual([f["max_length"] for f in fields], [200, 10000, 20, 0])

    def test_only_a_text_field_is_limited_in_length(self):
        rows = [_field("COUNT", "Integer", fieldLength=9), _field("STATE", "Single Selection", picklist="/api/v3/lookups/STATES", fieldLength=5)]
        fields = parse_form(rows, [_section("S", "COUNT", "STATE")], OPTIONS)["sections"][0]["fields"]
        self.assertEqual([f["max_length"] for f in fields], [0, 0])

    def test_a_field_carries_its_validators_for_the_form_to_check_except_those_it_says_itself(self):
        row = _field("TEXT", fieldValidators=[{"validatorName": "required", "variables": {}},
                                              {"validatorName": "maxlength", "variables": {"maxlength": "10"}},
                                              {"validatorName": "minlength", "variables": {"minlength": 3}},
                                              {"validatorName": "email", "variables": None}])
        field = parse_form([row], [_section("S", "TEXT")], {})["sections"][0]["fields"][0]
        self.assertEqual(field["validators"], [{"name": "minlength", "variables": {"minlength": "3"}}, {"name": "email", "variables": {}}])
        self.assertEqual((field["required"], field["max_length"]), (True, 10))

    def test_a_section_with_nothing_to_fill_in_is_not_shown(self):
        self.assertEqual(parse_form([_field("A", editability="NEVER")], [_section("Empty", "A")], {})["sections"], [])

    def test_a_field_that_two_sections_name_is_in_the_first(self):
        form = parse_form([_field("A")], [_section("One", "A"), _section("Two", "A")], {})
        self.assertEqual([s["title"] for s in form["sections"]], ["One"])

    def test_a_field_says_it_is_required_by_a_validator(self):
        rows = [_field("A", required=True), _field("B", fieldValidators=[{"validatorName": "required"}, {"validatorName": "maxlength"}]), _field("C")]
        form = parse_form(rows, [_section("S", "A", "B", "C")], {})
        self.assertEqual([f["required"] for f in form["sections"][0]["fields"]], [False, True, False])



class MatrixTests(unittest.TestCase):
    @staticmethod
    def _grid(layout, **names):
        return {"fields": [[{"__self__": f"/api/v3/workspaces/77/views/1/fields/{i}"} if i else None for i in row] for row in layout], **names}

    def test_a_grid_of_fields_keeps_its_rows_and_columns_named_by_the_layout(self):
        grid = self._grid([["A1", "B1"], ["A2", "B2"]], columns=[{"title": "Unit"}, {"title": "Material"}], rows=[{"title": "Specification"}, {"title": "Limits"}])
        rows = [_field(i) for i in ("A1", "B1", "A2", "B2")]
        form = parse_form(rows, [{"title": "Technical", "matrices": [grid]}], {})
        matrix = form["sections"][0]["matrices"][0]
        self.assertEqual((matrix["columns"], matrix["labels"]), (["Unit", "Material"], ["Specification", "Limits"]))
        self.assertEqual([[c["id"] for c in row] for row in matrix["rows"]], [["A1", "B1"], ["A2", "B2"]])
        self.assertEqual(form["sections"][0]["fields"], [])

    def test_a_grid_whose_columns_are_not_named_takes_the_titles_of_its_first_fields(self):
        form = parse_form([_field("A1"), _field("B1")], [{"title": "S", "matrices": [self._grid([["A1", "B1"]])]}], {})
        self.assertEqual(form["sections"][0]["matrices"][0]["columns"], ["A1", "B1"])

    def test_a_row_and_a_column_with_nothing_to_fill_in_are_left_out(self):
        grid = self._grid([["A1", None, "C1"], ["A2", None, "C2"], [None, None, None]])
        rows = [_field("A1"), _field("C1"), _field("A2", editability="NEVER"), _field("C2", editability="NEVER")]
        matrix = parse_form(rows, [{"title": "S", "matrices": [grid]}], {})["sections"][0]["matrices"][0]
        self.assertEqual([[c["id"] if c else None for c in row] for row in matrix["rows"]], [["A1", "C1"]])

    def test_a_grid_with_nothing_to_fill_in_is_not_shown(self):
        form = parse_form([_field("A1", editability="NEVER")], [{"title": "S", "matrices": [self._grid([["A1"]])]}], {})
        self.assertEqual(form["sections"], [])

class _Client:
    tenant = "acme"

    def __init__(self, rows, sections):
        self.rows, self.sections = rows, sections

    def get_json(self, path, accept="application/json"):
        return {"fields": self.rows} if path.endswith("/fields") else self.sections


class ServiceTests(unittest.TestCase):
    def test_the_form_is_made_of_the_fields_the_sections_and_the_options_of_the_workspace(self):
        from unittest import mock
        client = _Client([_field("TITLE"), _field("STATE", "Single Selection", picklist="/api/v3/lookups/STATES")],
                         [dict(_section("Basic", "TITLE", "STATE"), __self__="/api/v3/workspaces/77/sections/5")])
        with mock.patch("src.fm.workspace_form.WorkspaceService") as workspace:
            workspace.return_value.options.return_value = OPTIONS["STATES"]
            form = WorkspaceFormService(client).form("77")
        self.assertEqual([f["id"] for f in form["sections"][0]["fields"]], ["TITLE", "STATE"])
        self.assertEqual(form["sections"][0]["fields"][1]["options"], OPTIONS["STATES"])


if __name__ == "__main__":
    unittest.main()

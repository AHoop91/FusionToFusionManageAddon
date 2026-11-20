import unittest
from unittest import mock

from src.config.workspace_models import FieldNeed, WorkspaceKind, WorkspaceSchema
from src.fm.workspace import WorkspaceService
from src.fm.workspace_schema import Layout, problems, read_layout

SCHEMA = WorkspaceSchema(tabs=("ITEM_DETAILS", "GRID"),
                         fields=(FieldNeed("STATUS", "Single Selection", "Basic"), FieldNeed("OWNER"), FieldNeed("DUE", section="Dates")))


def _layout(**changes):
    layout = Layout(tabs={"ITEM_DETAILS": "Item", "GRID": "Grid"},
                    fields={"STATUS": {"title": "Status", "type": "Single Selection"}, "OWNER": {"title": "Owner", "type": "User"},
                            "DUE": {"title": "Due", "type": "Date"}},
                    sections={"STATUS": "Basic", "OWNER": "Basic", "DUE": "Dates"})
    for name, value in changes.items():
        setattr(layout, name, value)
    return layout


class ProblemsTests(unittest.TestCase):
    def test_a_workspace_with_everything_has_no_problems(self):
        self.assertEqual(problems(SCHEMA, _layout()), [])

    def test_an_empty_schema_asks_for_nothing(self):
        self.assertEqual(problems(WorkspaceSchema(), Layout()), [])

    def test_every_missing_tab_and_field_is_named_at_once(self):
        found = problems(SCHEMA, _layout(tabs={"ITEM_DETAILS": "Item"}, fields={"STATUS": {"title": "Status", "type": "Single Selection"}}))
        self.assertEqual(found, ["missing tabs: GRID", "missing fields: OWNER, DUE"])

    def test_a_field_of_the_wrong_type_is_named_with_both_types(self):
        layout = _layout()
        layout.fields["STATUS"]["type"] = "Text"
        self.assertEqual(problems(SCHEMA, layout), ["STATUS is of type Text, not Single Selection"])

    def test_the_type_and_the_section_are_compared_without_regard_to_case(self):
        layout = _layout()
        layout.fields["STATUS"]["type"] = "single selection"
        layout.sections["STATUS"] = " basic "
        self.assertEqual(problems(SCHEMA, layout), [])

    def test_a_field_in_the_wrong_section_is_named_with_both_sections(self):
        layout = _layout()
        layout.sections["DUE"] = "Basic"
        self.assertEqual(problems(SCHEMA, layout), ["DUE is in the section 'Basic', not 'Dates'"])

    def test_a_field_in_no_section_is_reported_as_unplaced(self):
        layout = _layout()
        del layout.sections["DUE"]
        self.assertEqual(problems(SCHEMA, layout), ["DUE is in the section '?', not 'Dates'"])


class _Client:
    tenant = "acme"

    def __init__(self, tabs, sections):
        self.answers = {"/api/v3/workspaces/9/tabs": tabs, "/api/v3/workspaces/9/sections": sections}

    def get_json(self, path, accept="application/json"):
        return self.answers[path]


class ReadLayoutTests(unittest.TestCase):
    def test_the_layout_holds_the_tabs_the_fields_and_the_title_of_each_fields_section(self):
        client = _Client([{"workspaceTabName": "ITEM_DETAILS", "name": "Item"}],
                         [{"__self__": "/api/v3/workspaces/9/sections/5", "title": "Basic",
                           "fields": [{"__self__": "/api/v3/workspaces/9/views/1/fields/STATUS"}]}])
        layout = read_layout(client, "9", [{"id": "STATUS", "title": "Status", "type": "Text"}])
        self.assertEqual((layout.tabs, layout.fields, layout.sections),
                         ({"ITEM_DETAILS": "Item"}, {"STATUS": {"title": "Status", "type": "Text"}}, {"STATUS": "Basic"}))


class ValidateTests(unittest.TestCase):
    KIND = WorkspaceKind("portfolio", ("view_items",), mapped=False, schema=SCHEMA)

    def _service(self, layout):
        service = WorkspaceService(mock.Mock())
        service.fields = mock.Mock(return_value=([], ""))
        patcher = mock.patch("src.fm.workspace.read_layout", return_value=layout)
        patcher.start()
        self.addCleanup(patcher.stop)
        service._client.get_json.side_effect = lambda path: (
            {"granted": ["permission.shortname.view_items"]} if path.endswith("permissions") else {"name": "Portfolio"})
        return service

    def test_a_workspace_missing_what_the_schema_needs_is_not_valid(self):
        with mock.patch("src.fm.workspace.parse_granted", return_value={"view_items"}):
            verdict = self._service(_layout(tabs={})).validate(self.KIND, "9")
        self.assertFalse(verdict["valid"])
        self.assertIn("'Portfolio' is not a Portfolio Management workspace: missing tabs: ITEM_DETAILS, GRID", verdict["message"])

    def test_a_workspace_with_everything_is_valid(self):
        with mock.patch("src.fm.workspace.parse_granted", return_value={"view_items"}):
            verdict = self._service(_layout()).validate(self.KIND, "9")
        self.assertTrue(verdict["valid"])


if __name__ == "__main__":
    unittest.main()

"""A failed save says which row is wrong and what to do, so the panel can mark that field."""

import unittest

from src.config.models import ConnectionSettings
from src.config.problems import problem_payload
from src.config.workspace_models import FieldMapping, StaticValue, WorkspaceConfig, WorkspaceSettings


def config(mappings=(), statics=(), component=""):
    return WorkspaceConfig(workspace_id="123", mappings=list(mappings), static_values=list(statics), component_field=component)


NUMBER = FieldMapping("item_number", "NUMBER")


class WorkspaceProblemTest(unittest.TestCase):
    def where(self, problems, text):
        found = [p for p in problems if text in p]
        self.assertEqual(len(found), 1, problems)
        return found[0].where

    def test_an_empty_mapping_row_names_its_row_and_each_missing_part(self):
        problems = config([NUMBER, FieldMapping("", "")]).validate()
        self.assertEqual(self.where(problems, "Mapped field 2: choose a Component Property"), {"area": "mapping", "row": 1, "part": "source"})
        self.assertEqual(self.where(problems, "Mapped field 2: choose a Fusion Manage Item Field"), {"area": "mapping", "row": 1, "part": "field"})

    def test_a_property_mapped_twice_points_at_the_second_row(self):
        problems = config([NUMBER, FieldMapping("name", "TITLE"), FieldMapping("name", "OTHER")]).validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("already used by mapped field 2", problems[0])
        self.assertEqual(problems[0].where, {"area": "mapping", "row": 2, "part": "source"})

    def test_a_field_filled_twice_points_at_the_later_place(self):
        problems = config([NUMBER, FieldMapping("name", "TITLE")], [StaticValue("TITLE", "x")]).validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("Default value 1", problems[0])
        self.assertEqual(problems[0].where, {"area": "static", "row": 0, "part": "field"})

    def test_a_default_value_needs_a_field(self):
        problems = config([NUMBER], [StaticValue("", "x")]).validate()
        self.assertEqual(problems[0].where, {"area": "static", "row": 0, "part": "field"})

    def test_item_number_missing_points_at_the_list(self):
        problems = config([FieldMapping("name", "TITLE")]).validate()
        self.assertEqual(self.where(problems, "Item Number is not mapped"), {"area": "mappings"})

    def test_item_number_without_a_field_is_reported_once(self):
        problems = config([FieldMapping("item_number", "")]).validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("choose a Fusion Manage Item Field", problems[0])

    def test_settings_add_the_workspace_to_where(self):
        settings = WorkspaceSettings()
        settings.workspaces["items"] = config([FieldMapping("", "")])
        problems = settings.validate()
        self.assertTrue(problems)
        self.assertTrue(all(p.where["workspace"] == "items" for p in problems))

    def test_connection_problems_name_their_input(self):
        problems = ConnectionSettings(client_id="").validate(require_tenant=False)
        self.assertEqual(problems[0].where, {"input": "f-client-id"})

    def test_payload_carries_message_and_place(self):
        problems = config([FieldMapping("", "")]).validate()
        payload = problem_payload(problems)
        self.assertEqual(payload[0]["message"], str(problems[0]))
        self.assertEqual(payload[0]["where"]["area"], "mapping")
        self.assertEqual(problem_payload(["plain"]), [{"message": "plain", "where": {}}])


if __name__ == "__main__":
    unittest.main()

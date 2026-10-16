import unittest
from unittest import mock

from src.fm.picklists import PicklistResolver

FIELDS = {"fields": [
    {"__self__": "/api/v3/workspaces/242/views/1/fields/TYPE", "picklist": "/api/v3/lookups/CUSTOM_LOOKUP_ITEM_TYPES"},
    {"__self__": "/api/v3/workspaces/242/views/1/fields/COMPONENT", "picklist": "/api/v3/lookups/COMPONENTS", "picklistFieldDefinition": "x"},
    {"__self__": "/api/v3/workspaces/242/views/1/fields/TITLE"},
    {"__self__": "/api/v3/workspaces/242/views/1/fields/ITEM_WEIGHT", "fieldPrecision": 3},
    {"__self__": "/api/v3/workspaces/242/views/1/fields/NOTE", "fieldPrecision": None},
]}
OPTIONS = {"items": [{"link": "/api/v3/lookups/CUSTOM_LOOKUP_ITEM_TYPES/options/6", "title": "Manufacturing"},
                     {"link": "/api/v3/lookups/CUSTOM_LOOKUP_ITEM_TYPES/options/7", "title": "Top Level Assembly"}], "totalCount": 2}


class PicklistTests(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()
        self.client.get_json.side_effect = lambda path: FIELDS if path.endswith("/fields") else OPTIONS
        self.resolver = PicklistResolver(self.client, "242")

    def test_option_found_by_title(self):
        self.assertEqual(self.resolver.link("TYPE", " top level assembly "), "/api/v3/lookups/CUSTOM_LOOKUP_ITEM_TYPES/options/7")

    def test_unknown_title_is_empty_and_other_fields_are_not_picklists(self):
        self.assertEqual(self.resolver.link("TYPE", "Nope"), "")
        self.assertIsNone(self.resolver.link("TITLE", "x"))
        self.assertIsNone(self.resolver.link("COMPONENT", "x"))   # links to a workspace; the component link is set separately

    def test_numbers_are_rounded_to_the_fields_precision(self):
        self.assertEqual(self.resolver.fit_number("ITEM_WEIGHT", "5.43342"), "5.433")
        self.assertEqual(self.resolver.fit_number("ITEM_WEIGHT", "12"), "12")
        self.assertEqual(self.resolver.fit_number("ITEM_WEIGHT", "2.5"), "2.5")
        self.assertEqual(self.resolver.fit_number("ITEM_WEIGHT", "abc"), "abc")
        self.assertEqual(self.resolver.fit_number("NOTE", "5.43342"), "5.43342")   # no limit stated

    def test_each_list_is_read_once(self):
        self.resolver.link("TYPE", "Manufacturing")
        self.resolver.link("TYPE", "Top Level Assembly")
        self.assertEqual(self.client.get_json.call_count, 2)   # the fields, then the options


class OptionsPageTests(unittest.TestCase):
    def test_a_page_carries_its_options_the_total_and_how_many_rows_it_held(self):
        from src.fm.workspace import WorkspaceService

        class Client:
            def get_json(self, path):
                self.path = path
                return {"totalCount": 120, "items": [{"link": "/api/v3/lookups/C/options/1", "title": "United States"}, {"link": ""}]}

        client = Client()
        page = WorkspaceService(client).options_page("C", 50, 50, "united st")
        self.assertEqual(page, {"options": [{"value": "/api/v3/lookups/C/options/1", "title": "United States"}], "total": 120, "raw": 2})
        self.assertIn("offset=50&limit=50&filter=united+st", client.path)


class FieldVisibilityTests(unittest.TestCase):
    def test_a_field_hidden_on_items_is_marked_not_shown(self):
        from src.fm.workspace import WorkspaceService

        class Client:
            def get_json(self, path):
                return {"fields": [{"__self__": "/api/v3/workspaces/1/fields/A", "name": "Shown", "visibility": "ALWAYS"},
                                   {"__self__": "/api/v3/workspaces/1/fields/B", "name": "Never", "visibility": "NEVER"},
                                   {"__self__": "/api/v3/workspaces/1/fields/C", "name": "Flag", "visibility": "ALWAYS", "hidden": True},
                                   {"__self__": "/api/v3/workspaces/1/fields/D", "name": "Calc", "derived": True},
                                   {"__self__": "/api/v3/workspaces/1/fields/E", "name": "Calc2", "formulaField": True, "derived": False},
                                   {"__self__": "/api/v3/workspaces/1/fields/F", "name": "Plain", "formulaField": False, "derived": False}]}

        fields, _ = WorkspaceService(Client()).fields("/api/v3/workspaces/1")
        self.assertEqual({f["id"]: f["shown"] for f in fields}, {"A": True, "B": False, "C": False, "D": True, "E": True, "F": True})
        self.assertEqual({f["id"] for f in fields if f["computed"]}, {"D", "E"})


if __name__ == "__main__":
    unittest.main()

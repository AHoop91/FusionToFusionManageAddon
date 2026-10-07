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


if __name__ == "__main__":
    unittest.main()

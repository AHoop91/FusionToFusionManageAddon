"""Parsers of Fusion Manage answers read an answer of an unexpected shape as empty: none of them crashes on it."""

import unittest

from src.config.export_models import ExportSettings
from src.config.workspace_models import WorkspaceConfig
from src.fm.attachments import parse_files
from src.fm.bom import parse_bom as parse_bom_lines
from src.fm.bom_view import parse_kinds, parse_viewdef
from src.fm.item_search import parse_members, parse_search
from src.fm.items import _rows
from src.fm.permissions import parse_granted
from src.fm.search_query import build_query
from src.fm.sections import parse_sections
from src.fm.tabs import parse_counts, parse_labels
from src.fusion_mfg.fusion_graphql_client import MfgApiError
from src.fusion_mfg.hub_lookup import find_hub_id
from src.fusion_mfg.properties import parse_definitions

# Whatever sits where an object or a list should be: nothing, text, an empty or a wrongly filled container.
ODD = (None, "x", 1, [], {}, [None, "x", 1, []], {"items": "x", "nodes": "x", "edges": "x", "attachments": "x", "permissions": "x",
                                                  "tabs": "x"}, {"items": [None, "x"], "nodes": [None, "x", {"item": "x"}], "edges": [None, "x"],
                                                                 "attachments": [None, "x"], "permissions": [None, {"name": 1}], "tabs": [None, "x"]})


class MalformedAnswerTests(unittest.TestCase):
    def check(self, parse, expected, *args):
        for data in ODD:
            with self.subTest(parse=parse.__name__, data=data):
                self.assertEqual(parse(data, *args), expected)

    def test_files_are_none(self):
        self.check(parse_files, [])

    def test_permissions_are_none(self):
        self.check(parse_granted, set())

    def test_search_hits_and_members_are_none(self):
        for data in ODD:
            with self.subTest(data=data):
                self.assertEqual(parse_search(data, "1", "2")["items"], [])
        self.check(parse_members, {"ids": [], "numbers": []})

    def test_bom_lines_are_none(self):
        self.check(parse_bom_lines, {})

    def test_rows_of_a_search_are_none(self):
        self.check(_rows, [])

    def test_tabs_are_none(self):
        self.check(parse_labels, {})
        self.check(parse_counts, {})

    def test_view_definitions_are_none(self):
        self.check(parse_viewdef, {})
        self.check(parse_kinds, {})

    def test_sections_are_none(self):
        self.check(parse_sections, {})

    def test_property_definitions_are_only_the_physical_ones(self):
        for data in (*ODD, {"hub": "x"}, {"hub": {"basePropertyDefinitionCollections": "x", "propertyDefinitionCollections": {"results": ["x", {"definitions": "x"}]}}}):
            with self.subTest(data=data):
                self.assertEqual({p["group"] for p in parse_definitions(data)}, {"physical"})

    def test_no_hub_in_an_answer_of_the_wrong_shape(self):
        for data in (*ODD, {"hubs": "x"}, {"hubs": {"results": [None, "x"]}}):
            with self.subTest(data=data):
                with self.assertRaises(MfgApiError):
                    find_hub_id(data, "Acme")

    def test_a_search_filter_of_the_wrong_shape_is_no_filter(self):
        for groups in ODD:
            with self.subTest(groups=groups):
                self.assertEqual(build_query("1", "", groups), "workspaceId=1")

    def test_stored_settings_of_the_wrong_shape_read_as_defaults(self):
        for data in ODD:
            with self.subTest(data=data):
                self.assertEqual(ExportSettings.from_dict(data), ExportSettings.from_dict(None))
        for rows in ("x", [None, "x"], {"a": 1}):
            with self.subTest(rows=rows):
                config = WorkspaceConfig.from_dict({"mappings": rows, "static_values": rows})
                self.assertEqual((config.mappings, config.static_values), ([], []))


if __name__ == "__main__":
    unittest.main()

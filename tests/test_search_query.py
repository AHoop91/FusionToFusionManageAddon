"""The query the Add Items picker sends to the Fusion Manage search."""

import unittest

from src.fm.search_query import build_query, clean_value, encode, field_id, search_path


def row(field, value, join="AND"):
    return {"field": field, "value": value, "join": join}


class QueryTests(unittest.TestCase):
    def test_nothing_typed_lists_the_whole_workspace(self):
        self.assertEqual(build_query("57"), "workspaceId=57")

    def test_text_is_anded_with_the_workspace(self):
        self.assertEqual(build_query("57", "Printer Bag"), '("Printer Bag") AND workspaceId=57')

    def test_one_row_is_a_field_clause(self):
        groups = [{"join": "AND", "filters": [row("country", "United States")]}]
        self.assertEqual(build_query("57", "", groups), '(ITEM_DETAILS:COUNTRY="United States") AND workspaceId=57')

    def test_rows_of_a_group_join_as_chosen_and_are_bracketed(self):
        groups = [{"join": "AND", "filters": [row("A", "1", "OR"), row("B", "2")]}]
        self.assertEqual(build_query("57", "", groups), "((ITEM_DETAILS:A=1 OR ITEM_DETAILS:B=2)) AND workspaceId=57")

    def test_groups_join_as_chosen_and_the_workspace_stays_outside(self):
        groups = [{"join": "OR", "filters": [row("A", "1")]}, {"join": "AND", "filters": [row("B", "2")]}]
        self.assertEqual(build_query("57", "", groups), "((ITEM_DETAILS:A=1 OR ITEM_DETAILS:B=2)) AND workspaceId=57")

    def test_rows_without_a_field_or_value_are_ignored(self):
        groups = [{"join": "AND", "filters": [row("", "1"), row("A", "  ")]}, {"join": "AND", "filters": [row("B", "2")]}]
        self.assertEqual(build_query("57", "", groups), "(ITEM_DETAILS:B=2) AND workspaceId=57")

    def test_text_and_filters_are_both_applied(self):
        groups = [{"join": "AND", "filters": [row("A", "1")]}]
        self.assertEqual(build_query("57", "bag", groups), "(bag AND ITEM_DETAILS:A=1) AND workspaceId=57")

    def test_a_value_cannot_add_operators(self):
        self.assertEqual(clean_value('x) OR workspaceId=1 ("'), "x OR workspaceId1")
        groups = [{"join": "AND", "filters": [row("A", "1) OR (workspaceId=9")]}]
        self.assertEqual(build_query("57", "", groups), '(ITEM_DETAILS:A="1 OR workspaceId9") AND workspaceId=57')

    def test_an_or_in_the_text_is_searched_for_not_obeyed(self):
        self.assertEqual(build_query("57", "foo OR bar"), '("foo OR bar") AND workspaceId=57')

    def test_a_field_id_is_upper_case_without_prefix_or_odd_characters(self):
        self.assertEqual(field_id("item_details:Part Number!"), "PARTNUMBER")
        self.assertEqual(field_id("MATERIAL_TYPE"), "MATERIAL_TYPE")

    def test_the_workspace_must_be_a_number(self):
        with self.assertRaises(ValueError):
            build_query("57 OR 1=1")


class PathTests(unittest.TestCase):
    def test_encoding_keeps_brackets_and_encodes_equals(self):
        self.assertEqual(encode("(A=1 OR B=2) AND workspaceId=57"), "(A%3D1+OR+B%3D2)+AND+workspaceId%3D57")

    def test_path_pages_and_sorts(self):
        path = search_path("57", "bag", None, 100, 100)
        self.assertEqual(path, "/api/v3/search-results?limit=100&offset=100&query=(bag)+AND+workspaceId%3D57"
                               "&revision=1&sort=createdOn+asc")


if __name__ == "__main__":
    unittest.main()

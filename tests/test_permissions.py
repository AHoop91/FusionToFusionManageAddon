import unittest
from unittest import mock

from src.fm.permissions import missing, parse_granted, title
from src.fm.tabs import TabService

PERMISSIONS = {"permissions": [{"name": "permission.shortname.view_items"}, {"name": "permission.shortname.view_bom"},
                               {"name": "permission.shortname.view_attachments"}]}
LABELS = [{"workspaceTabName": "PART_ATTACHMENTS", "name": "Files", "key": "Attachments"},
          {"workspaceTabName": "BOM_LIST", "name": None, "key": "Bill of Materials"},
          {"workspaceTabName": "BOM_WHERE_USED", "name": None, "key": "Where Used"}]
COUNTS = {"tabs": [{"name": "PART_ATTACHMENTS", "totalCount": 3}, {"name": "BOM_LIST", "totalCount": 5}]}


class PermissionTests(unittest.TestCase):
    def test_short_names(self):
        self.assertEqual(parse_granted(PERMISSIONS), {"view_items", "view_bom", "view_attachments"})
        self.assertEqual(parse_granted(None), set())

    def test_missing_and_title(self):
        self.assertEqual(missing(["view_items", "add_items"], {"view_items"}), ["add_items"])
        self.assertEqual(title("add_to_bom"), "Add To Bom")

    def test_tabs_are_allowed_by_permission(self):
        client = mock.Mock(tenant="T")
        client.get_json.side_effect = lambda path: COUNTS if "/items/" in path else LABELS
        TabService._labels_cache.clear()
        tabs = TabService(client).read("242", "1", parse_granted(PERMISSIONS))
        self.assertEqual(tabs["files"], {"label": "Files", "count": 3, "allowed": True})
        self.assertEqual(tabs["bom"]["label"], "Bill of Materials")
        self.assertFalse(tabs["whereused"]["allowed"])   # no view_where_used
        self.assertNotIn("changes", tabs)   # the workspace lists no such tab


if __name__ == "__main__":
    unittest.main()

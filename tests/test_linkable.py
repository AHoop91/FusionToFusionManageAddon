"""The linkable-items row written for an item added to a Bill of Materials, as Fusion Manage would answer it."""

import unittest

from src.fm.linkable import item_link, item_urn, linkable_row


class LinkableRowTests(unittest.TestCase):
    def test_the_row_names_the_item_in_the_bom_view_of_its_parent(self):
        self.assertEqual(linkable_row("57", "14669", "15719"), {
            "__self__": "/api/v3/workspaces/57/items/14669/views/5/linkable-items/15719",
            "urn": "urn:adsk.plm:tenant.workspace.item.view.linkable-item:{{tenant}}.57.14669.5.15719",
            "item": {"link": "/api/v3/workspaces/57/items/15719", "urn": "urn:adsk.plm:tenant.workspace.item:{{tenant}}.57.15719"}})

    def test_markers_of_items_not_yet_made_are_carried_as_they_are(self):
        row = linkable_row("57", "{{item:A}}", "{{item:B}}")
        self.assertTrue(row["__self__"].endswith("/items/{{item:A}}/views/5/linkable-items/{{item:B}}"))
        self.assertEqual(row["item"]["link"], "/api/v3/workspaces/57/items/{{item:B}}")

    def test_an_item_has_a_link_and_an_urn(self):
        self.assertEqual(item_link("57", "9"), "/api/v3/workspaces/57/items/9")
        self.assertEqual(item_urn("57", "9"), "urn:adsk.plm:tenant.workspace.item:{{tenant}}.57.9")


if __name__ == "__main__":
    unittest.main()

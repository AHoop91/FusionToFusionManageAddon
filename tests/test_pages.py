import unittest

from src.fm.item_view import cell_of, no_image
from src.fm.pages import field_id, item_page, link_page, tenant_of

BASE = "https://acme.autodeskplm360.net"
ITEM = {"urn": "urn:adsk.plm:tenant.workspace.item:ACME.57.14669", "link": "/api/v3/workspaces/57/items/14669"}
PAGE = (BASE + "/plm/workspaces/57/items/itemDetails?view=full&tab=details&mode=view&itemId="
        "urn%60adsk%2Cplm%60tenant%2Cworkspace%2Citem%60ACME%2C57%2C14669")


class PageTests(unittest.TestCase):
    def test_tenant_comes_from_the_urn(self):
        self.assertEqual(tenant_of(ITEM), "ACME")
        self.assertEqual(tenant_of({}), "")

    def test_item_page_from_link_or_self(self):
        self.assertEqual(item_page(BASE, ITEM), PAGE)
        self.assertEqual(item_page(BASE, {"urn": ITEM["urn"], "__self__": ITEM["link"]}), PAGE)

    def test_item_page_empty_when_not_understood(self):
        self.assertEqual(item_page(BASE, {"link": ITEM["link"]}), "")   # no tenant
        self.assertEqual(item_page(BASE, {"urn": ITEM["urn"], "link": "/api/v3/lookups/X/options/1"}), "")   # not an item

    def test_files_page(self):
        self.assertIn("/items/attachments?view=full&tab=attachments", item_page(BASE, ITEM, "attachments", "attachments"))

    def test_field_id(self):
        self.assertEqual(field_id({"__self__": "/api/v3/workspaces/57/views/1/fields/TITLE"}), "TITLE")
        self.assertEqual(field_id(None), "")


class PicklistLinkTests(unittest.TestCase):
    def pages(self, link):
        return link_page(BASE, "ACME", link)

    def test_picklist_of_items_becomes_links(self):
        node = {"__self__": "/api/v3/workspaces/57/views/1/fields/OWNER", "title": "Owner",
                "value": [{"link": "/api/v3/workspaces/57/items/9", "title": "9410-306 - STEP"}]}
        cell = cell_of(node, no_image, self.pages)
        self.assertEqual(cell["kind"], "links")
        self.assertEqual(cell["value"][0]["title"], "9410-306 - STEP")
        self.assertIn("ACME%2C57%2C9", cell["value"][0]["url"])

    def test_ordinary_picklist_stays_text(self):
        node = {"__self__": "/api/v3/workspaces/57/views/1/fields/TYPE", "title": "Type",
                "value": {"link": "/api/v3/lookups/TYPES/options/6", "title": "Manufacturing"}}
        cell = cell_of(node, no_image, self.pages)
        self.assertEqual((cell["kind"], cell["value"]), ("text", "Manufacturing"))


if __name__ == "__main__":
    unittest.main()

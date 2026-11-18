"""Where a design is used in the portfolio: read with the v1 search, compared by item number."""

import unittest
from types import SimpleNamespace

from src.fm.client import FmApiError
from src.fm.pages import page_url
from src.publish.products import ProductService

PRIMARY, LINK = "PRIMARY_COMPONENT", "COMPONENT"


def entry(key, text):
    return {"key": key, "fieldData": {"value": text, "formattedValue": text}}


def product(dms, *entries):
    return {"rowId": "0", "dmsId": dms, "fields": {"entry": list(entries)}}


class Client:
    """Answers the search with ``rows`` and a read of an item with its descriptor."""

    def __init__(self, rows, error=None):
        self.rows, self.error, self.sent, self.read = rows, error, [], []
        self.base_url, self.tenant, self.fields, self.descriptor = "https://acme.autodeskplm360.net", "acme", [], "Product "

    def send_json(self, method, path, body=None, content_type="application/json"):
        self.sent.append((method, path, body))
        if self.error:
            raise self.error
        return SimpleNamespace(status=200, headers={}, data={"totalResultCount": len(self.rows), "row": self.rows})

    def get_json(self, path, accept="application/json"):
        self.read.append(path)
        return {"descriptor": self.descriptor + path.rsplit("/", 1)[1], "fields": self.fields}


class UsageTests(unittest.TestCase):
    def test_the_primary_and_the_grid_column_are_asked_for(self):
        client = Client([])
        ProductService(client).usage("242", "PN-1", PRIMARY, LINK)
        body = client.sent[0][2]
        self.assertEqual(body["fields"], [{"fieldID": PRIMARY, "fieldTypeID": 0}, {"fieldID": LINK, "fieldTypeID": 2}])
        self.assertEqual(client.sent[0][1], "/api/rest/v1/workspaces/242/items/search")

    def test_a_primary_component_and_a_variant_are_told_apart_and_named(self):
        client = Client([product(7, entry(PRIMARY, "PN-1 - Axle")), product(8, entry(PRIMARY, "PN-2 - Other"), entry(LINK, "PN-1 - Axle"), entry(LINK, "PN-1 - Axle"))])
        found = ProductService(client).usage("242", "pn-1", PRIMARY, LINK)
        page = lambda item: page_url("https://acme.autodeskplm360.net", "acme", "242", item)
        self.assertEqual(found["primary"], [{"id": "7", "number": "", "name": "Product 7", "url": page("7"), "picture": "", "component": ""}])
        self.assertEqual(found["variants"], [{"id": "8", "number": "", "name": "Product 8", "url": page("8"), "picture": "", "component": "", "rows": 2}])
        self.assertTrue(found["variants_checked"])

    def test_a_product_descriptor_is_given_as_a_number_and_a_name(self):
        client = Client([product(7, entry(PRIMARY, "PN-1"))])
        client.descriptor = "24-000002 - Joint "
        card = ProductService(client).usage("242", "PN-1", PRIMARY, "")["primary"][0]
        self.assertEqual((card["number"], card["name"]), ("24-000002", "Joint 7"))

    def test_the_search_is_sorted_on_the_primary_field_as_the_service_needs_a_sort(self):
        client = Client([])
        ProductService(client).usage("242", "PN-1", PRIMARY, LINK)
        self.assertEqual(client.sent[0][2]["sort"], [{"fieldID": PRIMARY, "fieldTypeID": 0, "sortDescending": False}])

    def test_a_product_gives_the_link_of_the_picture_it_holds(self):
        client = Client([product(7, entry(PRIMARY, "PN-1"))])
        link = "/api/v3/workspaces/242/items/7/field-values/PHOTO/image/3"
        client.fields = [{"__self__": "/api/v3/workspaces/242/views/1/fields/PHOTO", "value": {"link": link}},
                         {"__self__": "/api/v3/workspaces/242/views/1/fields/OWNER", "value": {"link": "/api/v3/users/9"}}]
        self.assertEqual(ProductService(client).usage("242", "PN-1", PRIMARY, "")["primary"][0]["picture"], link)

    def test_a_product_gives_the_link_of_its_primary_component(self):
        client = Client([product(7, entry(PRIMARY, "PN-1"))])
        link = "/api/v3/workspaces/57/items/15677"
        client.fields = [{"__self__": "/api/v3/workspaces/242/views/1/fields/" + PRIMARY, "value": {"link": link, "title": "PN-1"}}]
        self.assertEqual(ProductService(client).usage("242", "PN-1", PRIMARY, "")["primary"][0]["component"], link)

    def test_a_longer_number_is_not_the_design(self):
        found = ProductService(Client([product(7, entry(PRIMARY, "PN-10 - Axle"), entry(LINK, "PN-100"))])).usage("242", "PN-1", PRIMARY, LINK)
        self.assertEqual((found["primary"], found["variants"]), ([], []))

    def test_a_design_used_nowhere_has_nothing_and_no_item_is_read(self):
        client = Client([product(7, entry(PRIMARY, "PN-2"))])
        found = ProductService(client).usage("242", "PN-1", PRIMARY, LINK)
        self.assertEqual((found["primary"], found["variants"]), ([], []))
        self.assertEqual(client.read, [])

    def test_without_a_variants_column_only_the_primary_is_looked_for_and_it_is_said(self):
        client = Client([product(7, entry(PRIMARY, "PN-1"))])
        found = ProductService(client).usage("242", "PN-1", PRIMARY, "")
        self.assertEqual(client.sent[0][2]["fields"], [{"fieldID": PRIMARY, "fieldTypeID": 0}])
        self.assertFalse(found["variants_checked"])
        self.assertEqual(len(found["primary"]), 1)

    def test_a_failed_search_raises_and_is_not_an_empty_answer(self):
        with self.assertRaises(FmApiError):
            ProductService(Client([], FmApiError("401", 401))).usage("242", "PN-1", PRIMARY, LINK)


if __name__ == "__main__":
    unittest.main()

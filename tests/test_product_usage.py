"""Where a design is used in the portfolio: read with the v1 search, compared by item number."""

import unittest
from types import SimpleNamespace

from src.fm.client import FmApiError
from src.fm.pages import page_url
from src.publish.products import NotAllowed, ProductService

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


class RefusedClient(Client):
    """A client whose app Fusion Manage does not accept: the v1 search says ``search`` and a read of the workspace says ``read``."""

    def __init__(self, search, read):
        super().__init__([], FmApiError("search", search))
        self.read_error = FmApiError("read", read)

    def get_json(self, path, accept="application/json"):
        if path == "/api/v3/workspaces/242":
            raise self.read_error
        return super().get_json(path, accept)


class NotAllowedTests(unittest.TestCase):
    def usage(self, client):
        return ProductService(client).usage("242", "PN-1", PRIMARY, LINK)

    def test_a_401_or_403_from_the_search_is_not_allowed(self):
        for status in (401, 403):
            with self.subTest(status=status), self.assertRaises(NotAllowed):
                self.usage(Client([], FmApiError("x", status)))

    def test_a_500_is_not_allowed_when_the_v3_api_refuses_the_app_as_well(self):
        with self.assertRaises(NotAllowed):
            self.usage(RefusedClient(500, 401))

    def test_a_500_is_an_error_as_it_is_when_the_v3_api_accepts_the_app(self):
        with self.assertRaises(FmApiError) as caught:
            self.usage(Client([], FmApiError("down", 500)))
        self.assertEqual(caught.exception.status, 500)

    def test_a_500_is_an_error_as_it_is_when_the_workspace_cannot_be_read_for_another_reason(self):
        with self.assertRaises(FmApiError):
            self.usage(RefusedClient(500, 404))


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
            ProductService(Client([], FmApiError("404", 404))).usage("242", "PN-1", PRIMARY, LINK)


if __name__ == "__main__":
    unittest.main()

"""Opening the Fusion design of a component: the lineage id read from its item, and the open itself."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.fm.client import FmApiError
from src.fm.components import ComponentService

LINEAGE = "urn:adsk.wipprod:dm.lineage:4A7qrWmaTuG0eOal8ycK3w"
LINK = "/api/v3/workspaces/57/items/15677"


def item(lineage=LINEAGE, asset=None):
    data = {"sections": [{"fields": []}]}
    for field, value in (("LINEAGE_URN", lineage), ("ASSET_URN", asset)):
        if value is not None:
            data["sections"][0]["fields"].append({"__self__": f"/api/v3/workspaces/57/items/15677/views/1/fields/{field}", "value": value})
    return data


class DesignFileTests(unittest.TestCase):
    def read(self, data, link=LINK):
        client = mock.Mock()
        client.get_json.return_value = data
        return ComponentService(client).design_file(link), client

    def test_the_lineage_urn_field_is_the_design(self):
        found, client = self.read(item())
        self.assertEqual(found, LINEAGE)
        client.get_json.assert_called_once_with(LINK)

    def test_an_item_with_no_design_raises(self):
        with self.assertRaises(FmApiError):
            self.read(item(None))

    def test_an_item_that_names_no_lineage_is_not_a_design(self):
        with self.assertRaises(FmApiError):
            self.read(item("not a urn"))

    def test_a_link_that_is_not_an_item_is_refused_before_a_read(self):
        client = mock.Mock()
        with self.assertRaises(FmApiError):
            ComponentService(client).design_file("/api/v3/users/9")
        client.get_json.assert_not_called()


class AssetTests(unittest.TestCase):
    def read(self, data, link=LINK):
        client = mock.Mock()
        client.get_json.return_value = data
        return ComponentService(client).asset(link), client

    def test_the_asset_urn_field_is_the_asset(self):
        found, client = self.read(item(asset="gEDHlC30rZcLLOTVGJMj9m_aga"))
        self.assertEqual(found, "gEDHlC30rZcLLOTVGJMj9m_aga")
        client.get_json.assert_called_once_with(LINK)

    def test_an_item_with_no_asset_urn_raises(self):
        for data in (item(), item(asset="")):
            with self.assertRaises(FmApiError):
                self.read(data)

    def test_a_link_that_is_not_an_item_is_refused_before_a_read(self):
        client = mock.Mock()
        with self.assertRaises(FmApiError):
            ComponentService(client).asset("/api/v3/users/9")
        client.get_json.assert_not_called()


class RevisionTests(unittest.TestCase):
    def test_the_revision_and_state_of_the_record(self):
        client = mock.Mock()
        client.get_json.return_value = {"version": "[REV:C]", "versionId": "C", "lifecycle": {"title": "Production"}}
        self.assertEqual(ComponentService(client).revision_and_state(LINK), ("[REV:C]", "Production"))
        client.get_json.assert_called_once_with(LINK)


class OpenTests(unittest.TestCase):
    def setUp(self):
        from tests.without_fusion import fusion_modules_stubbed
        with fusion_modules_stubbed():
            from src.ui.actions.product_actions import open_design_file
        self.open = open_design_file

    def app(self, found):
        data = mock.Mock()
        data.findFileById.return_value = found
        return SimpleNamespace(data=data, documents=mock.Mock())

    def test_the_file_is_found_by_its_id_and_opened(self):
        app = self.app("FILE")
        self.open({"file": LINEAGE}, lambda: app)
        app.data.findFileById.assert_called_once_with(LINEAGE)
        app.documents.open.assert_called_once_with("FILE", True)

    def test_a_file_the_hub_does_not_have_is_said(self):
        app = self.app(None)
        with self.assertRaises(ValueError):
            self.open({"file": LINEAGE}, lambda: app)
        app.documents.open.assert_not_called()

    def test_an_id_that_is_not_a_design_is_refused_before_fusion_is_asked(self):
        app = self.app("FILE")
        for bad in ("", "x", "urn:adsk.wipprod:dm.lineage:a b"):
            with self.assertRaises(ValueError):
                self.open({"file": bad}, lambda: app)
        app.data.findFileById.assert_not_called()


if __name__ == "__main__":
    unittest.main()

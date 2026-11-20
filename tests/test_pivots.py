"""The derived fields a linking field takes from the item it links to."""

import unittest

from src.fm.client import FmApiError
from src.fm.pivots import Derived, PivotService, parse_pivot

ANSWER = {"__self__": "/api/v3/workspaces/242/views/1/pivots/COMPONENT", "sections": [
    {"link": "/api/v3/workspaces/242/sections/551", "title": "Basic", "fields": [
        {"__self__": "/api/v3/workspaces/242/views/1/fields/COMPONENT_ASSET_URN", "title": "Component Asset Urn", "value": "UsFPLu4xBYa4K6nk8tijD3_aga"},
        {"__self__": "/api/v3/workspaces/242/views/1/fields/COMPONENT_LINEAGE_URN", "title": "Component Lineage Urn",
         "value": "urn:adsk.wipprod:dm.lineage:4A7qrWmaTuG0eOal8ycK3w"}]}]}


class Client:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def get_json(self, path, accept="application/json"):
        self.asked.append(path)
        return self.answer


class PivotTests(unittest.TestCase):
    def test_each_derived_field_has_its_value_and_its_section(self):
        self.assertEqual(parse_pivot(ANSWER), [Derived("COMPONENT_ASSET_URN", "UsFPLu4xBYa4K6nk8tijD3_aga", "/api/v3/workspaces/242/sections/551"),
                                               Derived("COMPONENT_LINEAGE_URN", "urn:adsk.wipprod:dm.lineage:4A7qrWmaTuG0eOal8ycK3w",
                                                       "/api/v3/workspaces/242/sections/551")])

    def test_the_pivot_of_the_linking_field_is_asked_for_the_linked_item(self):
        client = Client(ANSWER)
        PivotService(client).derived("242", "COMPONENT", "15745")
        self.assertEqual(client.asked, ["/api/v3/workspaces/242/views/1/pivots/COMPONENT?pivotItemId=15745"])

    def test_a_field_with_no_id_or_a_section_with_no_link_is_an_error_not_a_blank_entry(self):
        for sections in ([{"link": "/s/1", "fields": [{"value": "x"}]}], [{"fields": [{"__self__": "/f/ASSET", "value": "x"}]}]):
            with self.assertRaises(FmApiError):
                parse_pivot({"sections": sections})

    def test_a_pivot_with_no_derived_fields_gives_none(self):
        self.assertEqual(parse_pivot({"sections": []}), [])


if __name__ == "__main__":
    unittest.main()

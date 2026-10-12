"""Looking a component up in Fusion Manage gives one state each: new, found, several, unknown or unchecked."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.fm.client import FmApiError
from src.sync import item_compare
from src.sync.item_compare import compare_item, compare_with_item, item_number_of, lookup_item
from src.sync.property_compare import FOUND, MULTIPLE, NEW, UNKNOWN

CFG = SimpleNamespace(workspace_id="242", mappings=[])
ITEM = {"item_number": "PN-1", "part_number": "PN-1"}


def service(hits=None, error=None):
    """An ItemService whose search finds ``hits`` (or fails with ``error``) and whose read gives a fixed set of values."""
    class Fake:
        def __init__(self, _fm):
            pass

        def search(self, _workspace, _number):
            if error:
                raise error
            return hits

        def read(self, _workspace, item_id):
            return {"read": item_id}

    return mock.patch.object(item_compare, "ItemService", Fake)


class LookupTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(item_compare, "display_values", side_effect=lambda values: values)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_number_is_the_item_number_else_the_part_number(self):
        self.assertEqual(item_number_of({"item_number": " A ", "part_number": "B"}), "A")
        self.assertEqual(item_number_of({"item_number": "", "part_number": "B"}), "B")
        self.assertEqual(item_number_of({}), "")

    def test_without_a_workspace_nothing_is_asked(self):
        lookup = lookup_item(ITEM, SimpleNamespace(workspace_id="", mappings=[]), None)
        self.assertEqual(lookup.info["state"], "unchecked")
        self.assertIn("Items workspace", lookup.info["message"])
        self.assertIsNone(lookup.values)

    def test_without_a_number_nothing_is_asked(self):
        lookup = lookup_item({}, CFG, None)
        self.assertEqual(lookup.info["state"], "unchecked")
        self.assertIn("no item number", lookup.info["message"])

    def test_no_hit_is_a_new_item(self):
        with service(hits=[]):
            lookup = lookup_item(ITEM, CFG, None)
        self.assertEqual(lookup.info["state"], NEW)
        self.assertIsNone(lookup.values)

    def test_one_hit_is_found_and_read(self):
        with service(hits=[{"id": "7"}]):
            lookup = lookup_item(ITEM, CFG, None)
        self.assertEqual((lookup.info["state"], lookup.info["item_id"], lookup.info["candidates"]), (FOUND, "7", []))
        self.assertEqual(lookup.values, {"read": "7"})

    def test_several_hits_wait_for_a_choice(self):
        with service(hits=[{"id": "7"}, {"id": "8"}]):
            lookup = lookup_item(ITEM, CFG, None)
        self.assertEqual(lookup.info["state"], MULTIPLE)
        self.assertEqual([c["id"] for c in lookup.info["candidates"]], ["7", "8"])
        self.assertIsNone(lookup.values)

    def test_a_choice_among_several_is_found_and_read(self):
        with service(hits=[{"id": "7"}, {"id": "8"}]):
            lookup = lookup_item(ITEM, CFG, None, chosen="8")
        self.assertEqual((lookup.info["state"], lookup.info["item_id"]), (FOUND, "8"))
        self.assertEqual(lookup.values, {"read": "8"})

    def test_a_failure_of_fusion_manage_is_unknown(self):
        with service(error=FmApiError("down")):
            lookup = lookup_item(ITEM, CFG, None)
        self.assertEqual(lookup.info["state"], UNKNOWN)
        self.assertIn("down", lookup.info["message"])


class CompareTests(unittest.TestCase):
    def test_compare_item_is_the_lookup_then_the_comparison(self):
        rows = [{"name": "Mass", "value": "1"}]
        with service(hits=[{"id": "7"}]), mock.patch.object(item_compare, "display_values", side_effect=lambda values: values):
            whole = compare_item(rows, ITEM, CFG, None, with_values=True)
            lookup = lookup_item(ITEM, CFG, None)
            parts = compare_with_item(rows, ITEM, CFG, lookup, with_values=True)
        self.assertEqual(whole, parts)
        self.assertEqual(whole["values"], {"read": "7"})


if __name__ == "__main__":
    unittest.main()

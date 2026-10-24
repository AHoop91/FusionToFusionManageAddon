"""The shared reads of a publish run: several components or item numbers to a request."""

import unittest
from unittest import mock

from src.fm.client import FmApiError
from src.publish import read_ahead
from src.publish.read_ahead import ReadAhead, component_id_of

SUMMARY = {"component_id": "root-id", "composition": "DESIGN"}


def item(number, component_id="", root=False):
    return {"item_number": number, "id": component_id, "root": root}


def ahead(items, cancelled=lambda: False, workspace_id="242"):
    return ReadAhead(items, SUMMARY, None, None, workspace_id, "t1", False, cancelled)


class ReadAheadTests(unittest.TestCase):
    def test_the_root_item_is_the_designs_own_component(self):
        self.assertEqual(component_id_of(item("A", root=True), SUMMARY), "root-id")
        self.assertEqual(component_id_of(item("B", "c2"), SUMMARY), "c2")

    def test_components_are_read_several_to_a_request_and_each_item_takes_its_own(self):
        asked = []

        def fake(_client, _summary, ids, _time, _physical):
            asked.append(list(ids))
            return {cid: {"properties": [], "id": cid} for cid in ids}

        items = [item(f"PN-{n}", f"c{n}") for n in range(6)]
        with mock.patch.object(read_ahead, "read_publish_components", fake), mock.patch.object(read_ahead, "publish_batch_size", lambda _p: 4):
            with ahead(items, workspace_id="") as shared:
                self.assertEqual(shared.read("c5")["id"], "c5")
        self.assertEqual(sorted(len(ids) for ids in asked), [2, 4])

    def test_an_item_without_a_number_or_an_id_is_not_read(self):
        asked = []
        items = [item("", "c1"), item("PN-2", ""), item("PN-3", "c3")]
        with mock.patch.object(read_ahead, "read_publish_components", lambda _c, _s, ids, _t, _p: asked.extend(ids) or {i: {} for i in ids}):
            with ahead(items, workspace_id="") as shared:
                with self.assertRaises(ValueError):
                    shared.read("c1")
        self.assertEqual(asked, ["c3"])

    def test_a_component_that_failed_raises_its_error(self):
        error = FmApiError("refused")
        with mock.patch.object(read_ahead, "read_publish_components", lambda _c, _s, ids, _t, _p: {i: error for i in ids}):
            with ahead([item("PN-1", "c1")], workspace_id="") as shared:
                with self.assertRaises(FmApiError):
                    shared.read("c1")

    def test_numbers_are_searched_together_and_found_by_trimmed_lower_case_number(self):
        class Items:
            def __init__(self, _fm):
                pass

            def find_many(self, _workspace, numbers):
                return {n.lower(): [{"id": "1"}] for n in numbers if n != "PN-9"}

        with mock.patch.object(read_ahead, "read_publish_components", lambda *_a: {}), mock.patch.object(read_ahead, "ItemService", Items):
            with ahead([item("PN-1", "c1"), item("PN-9", "c9")]) as shared:
                self.assertEqual(shared.found("PN-1"), [{"id": "1"}])
                self.assertIsNone(shared.found("PN-9"))
                self.assertIsNone(shared.found("PN-404"))   # never searched: the item looks for itself

    def test_a_failed_search_leaves_every_item_to_look_for_itself(self):
        class Items:
            def __init__(self, _fm):
                pass

            def find_many(self, _workspace, _numbers):
                raise FmApiError("503")

        with mock.patch.object(read_ahead, "read_publish_components", lambda *_a: {}), mock.patch.object(read_ahead, "ItemService", Items):
            with ahead([item("PN-1", "c1")]) as shared:
                self.assertIsNone(shared.found("PN-1"))

    def test_nothing_is_asked_once_the_run_is_cancelled(self):
        asked = []
        with mock.patch.object(read_ahead, "read_publish_components", lambda *_a: asked.append(1) or {}):
            with ahead([item("PN-1", "c1")], cancelled=lambda: True, workspace_id="") as shared:
                with self.assertRaises(RuntimeError):
                    shared.read("c1")
        self.assertEqual(asked, [])


if __name__ == "__main__":
    unittest.main()

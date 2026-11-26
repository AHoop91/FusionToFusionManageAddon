"""The versions a request names are read together, not one item after another (a read takes about a second, and each waited for the one before it)."""

import tempfile
import threading
import unittest

from src.publish.sender import Dispatcher


class Waiting:
    """A client whose item reads only answer once three are under way together: a read made after another one's answer would time out."""

    def __init__(self):
        self.together = threading.Barrier(3, timeout=5)
        self.paths = []

    def get_json(self, path, accept=""):
        self.paths.append(path)
        self.together.wait()
        return {"urn": "urn:adsk.plm:tenant.workspace.item:TEST.57.1", "version": "1"}

    def with_cancel(self, token):
        return self


class ItemFactsTests(unittest.TestCase):
    def test_the_items_of_a_request_are_read_together_and_once(self):
        with tempfile.TemporaryDirectory() as folder:
            fm = Waiting()
            dispatcher = Dispatcher(folder, fm, "57")
            dispatcher._read_facts(["1", "2", "3", "2"])
            self.assertEqual(sorted(fm.paths), [f"/api/v3/workspaces/57/items/{i}" for i in ("1", "2", "3")])
            dispatcher._read_facts(["1", "2", "3"])
            self.assertEqual(len(fm.paths), 3, "what was read is not read again")
            self.assertEqual(dispatcher._item_facts("2")["version"], "1")


class MarkerValueTests(unittest.TestCase):
    def test_an_item_marker_keeps_its_id_even_when_empty_and_a_missing_version_is_left_out(self):
        with tempfile.TemporaryDirectory() as folder:
            dispatcher = Dispatcher(folder, Waiting(), "57")
            dispatcher._item_id = lambda number: ""
            dispatcher._item_facts = lambda item_id: {"version": "", "tenant": ""}
            request = {"url": "/items/{{item:A}}/versions/{{version:A}}"}
            self.assertEqual(dispatcher._values(request), {("item", "a"): ""})


if __name__ == "__main__":
    unittest.main()

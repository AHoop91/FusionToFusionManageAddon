import json
import os
import tempfile
import unittest

from src.fm.client import FmApiError, SendResult
from src.publish.placeholders import Unresolved, key_of, markers, resolve
from src.publish.runner import DONE, ERROR
from src.publish.sender import SEND_LOG, SendRun, created_id, load_plan


class PlaceholderTests(unittest.TestCase):
    def test_markers_are_found_in_urls_and_nested_bodies(self):
        request = {"url": "/items/{{item:A}}/bom-items", "body": {"item": {"link": "/items/{{item:B}}"}, "list": ["{{tenant}}"]}}
        self.assertEqual(markers(request), {key_of("item", "A"), key_of("item", "B"), ("tenant", "")})

    def test_resolve_fills_every_marker_and_item_numbers_ignore_case(self):
        request = {"url": "/items/{{item:PN-1}}", "body": ["{{version:pn-1}}"]}
        values = {key_of("item", "pn-1"): "7", key_of("version", "PN-1"): "[REV:w]"}
        self.assertEqual(resolve(request, values), {"url": "/items/7", "body": ["[REV:w]"]})

    def test_resolve_names_what_is_missing(self):
        with self.assertRaises(Unresolved) as caught:
            resolve({"url": "/items/{{item:A}}/{{edge:A>B@1}}"}, {})
        self.assertEqual(len(caught.exception.keys), 2)


class CreatedIdTests(unittest.TestCase):
    def test_id_comes_from_the_location_header_or_the_answer(self):
        self.assertEqual(created_id(SendResult(201, {"location": "https://t/api/v3/workspaces/1/items/55"}, None)), "55")
        self.assertEqual(created_id(SendResult(201, {}, {"__self__": "/api/v3/workspaces/1/items/56"})), "56")
        self.assertEqual(created_id(SendResult(201, {}, None)), "")


class FakeFm:
    """Records the writes; creates items 100, 101, ... and can refuse one url."""

    tenant = "t"

    def __init__(self, refuse=""):
        self.sent = []
        self.refuse = refuse
        self._next = 100

    def send_json(self, method, path, body=None):
        if self.refuse and self.refuse in path:
            raise FmApiError("Fusion Manage returned 400 for " + path, 400)
        self.sent.append((method, path, body))
        if method == "POST" and path.endswith("/items"):
            self._next += 1
            return SendResult(201, {"Location": f"https://t/api/v3/workspaces/57/items/{self._next}"}, None)
        return SendResult(200, {}, None)

    def get_json(self, path, accept=""):
        return {"urn": "urn:adsk.plm:tenant.workspace.item:TEST.57.1", "version": "[REV:w]"}


def write_folder(root, items, boms):
    manifest = {"root": "A", "workspace_id": "57", "tenant": "t", "items": {}}
    for number, request in items.items():
        rel = os.path.join("items", number, "item.request.json")
        os.makedirs(os.path.join(root, "items", number))
        with open(os.path.join(root, rel), "w") as handle:
            json.dump(request, handle)
        manifest["items"][number] = {"id": "", "state": "new", "request": rel}
    os.makedirs(os.path.join(root, "bom"))
    for parent, requests in boms.items():
        with open(os.path.join(root, "bom", parent + ".bom.request.json"), "w") as handle:
            json.dump({"parent": parent, "requests": requests}, handle)
    with open(os.path.join(root, "manifest.json"), "w") as handle:
        json.dump(manifest, handle)


def create(number):
    return {"method": "POST", "url": "/api/v3/workspaces/57/items", "body": {"sections": [], "n": number}}


def bom_add(parent, child):
    return {"method": "POST", "url": f"/api/v3/workspaces/57/items/{{{{item:{parent}}}}}/bom-items",
            "body": {"item": {"link": f"/api/v3/workspaces/57/items/{{{{item:{child}}}}}", "version": f"{{{{version:{child}}}}}"},
                     "urn": "urn:x:{{tenant}}.57.{{item:%s}}" % child, "itemNumber": 1}}


class SendRunTests(unittest.TestCase):
    def run_send(self, fm, items, boms):
        with tempfile.TemporaryDirectory() as root:
            write_folder(root, items, boms)
            run = SendRun(root, load_plan(root), fm)
            run.work()
            with open(os.path.join(root, SEND_LOG)) as handle:
                logged = json.load(handle)
            return run, logged

    def test_items_are_created_before_the_bom_that_names_their_new_ids(self):
        fm = FakeFm()
        run, logged = self.run_send(fm, {"A": create("A"), "B": create("B")}, {"A": [bom_add("A", "B")]})
        self.assertEqual(run.phase, DONE)
        method, path, body = fm.sent[-1]
        self.assertEqual(path, "/api/v3/workspaces/57/items/101/bom-items")
        self.assertEqual(body["item"], {"link": "/api/v3/workspaces/57/items/102", "version": "[REV:w]"})
        self.assertEqual(body["urn"], "urn:x:TEST.57.102")
        self.assertEqual(len(logged), 3)

    def test_every_item_is_sent_before_any_bom_line(self):
        fm = FakeFm()
        items = {n: create(n) for n in ("A", "B", "C", "D")}
        self.run_send(fm, items, {"A": [bom_add("A", "B")], "C": [bom_add("C", "D")]})
        kinds = ["bom" if p.endswith("/bom-items") else "item" for m, p, b in fm.sent]
        self.assertEqual(kinds, ["item"] * 4 + ["bom"] * 2)

    def test_a_failed_item_stops_its_bom_but_not_the_others(self):
        fm = FakeFm(refuse="?bad")
        run, _ = self.run_send(fm, {"A": create("A"), "B": {"method": "POST", "url": "/api/v3/workspaces/57/items?bad", "body": {}}},
                               {"A": [bom_add("A", "B")]})
        self.assertEqual([row["status"] for row in run.rows], ["done", "error", "error"])   # A created, B refused, A's BOM names B
        self.assertIn("B", run.rows[-1]["detail"])
        self.assertEqual(sum(1 for m, p, b in fm.sent if p.endswith("/bom-items")), 0)

    def test_sending_again_skips_what_was_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            write_folder(root, {"A": create("A")}, {})
            SendRun(root, load_plan(root), FakeFm()).work()
            fm = FakeFm()
            run = SendRun(root, load_plan(root), fm)
            run.work()
            self.assertEqual(fm.sent, [])
            self.assertEqual(run.phase, DONE)

    def test_an_old_folder_without_the_item_list_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "manifest.json"), "w") as handle:
                json.dump({"root": "A"}, handle)
            with self.assertRaises(Exception):
                load_plan(root)


if __name__ == "__main__":
    unittest.main()

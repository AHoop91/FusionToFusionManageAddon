"""Reading a publish folder to send it: what is checked before anything is sent."""

import json
import os
import tempfile
import unittest

from src.fm.client import FmApiError
from src.publish.sender import FolderError, Dispatcher, load_plan, was_cancelled

REQUEST = {"method": "POST", "url": "/api/v3/workspaces/1/items", "body": {}}


class Folder(tempfile.TemporaryDirectory):
    """A publish folder: the manifest, and the files it names."""

    def put(self, relative, data):
        path = os.path.join(self.name, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def manifest(self, items):
        self.put("manifest.json", {"root": "A", "workspace_id": "1", "items": items})


class LoadPlanTests(unittest.TestCase):
    def folder(self):
        folder = Folder()
        self.addCleanup(folder.cleanup)
        return folder

    def test_the_requests_of_the_items_and_the_boms_are_read(self):
        folder = self.folder()
        folder.put("items/A/item.request.json", REQUEST)
        folder.manifest({"A": {"request": "items/A/item.request.json"}, "B": {"request": ""}})
        folder.put("bom/A.bom.request.json", {"parent": "A", "requests": [{"method": "DELETE", "url": "/x", "body": None}]})
        plan = load_plan(folder.name)
        self.assertEqual([i["number"] for i in plan["items"]], ["A"])   # B has no request: nothing was to be sent
        self.assertEqual(plan["items"][0]["request"], REQUEST)
        self.assertEqual(plan["boms"], [{"parent": "A", "requests": [{"method": "DELETE", "url": "/x", "body": None}]}])

    def test_a_folder_with_no_manifest_is_not_a_publish_folder(self):
        with self.assertRaisesRegex(FolderError, "manifest.json is missing"):
            load_plan(self.folder().name)

    def test_a_manifest_that_is_not_what_this_version_writes_is_refused(self):
        for manifest in ({"root": "A"}, {"items": []}, {"items": "x"}, [], "text"):
            with self.subTest(manifest=manifest):
                folder = self.folder()
                folder.put("manifest.json", manifest)
                with self.assertRaises(FolderError):
                    load_plan(folder.name)

    def test_a_manifest_that_is_not_json_is_a_folder_error(self):
        folder = self.folder()
        with open(os.path.join(folder.name, "manifest.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaisesRegex(FolderError, "Could not read manifest.json"):
            load_plan(folder.name)

    def test_a_request_file_outside_the_folder_is_never_read(self):
        outside = self.folder()
        outside.put("secret.json", REQUEST)
        folder = self.folder()
        for relative in ("../" + os.path.basename(outside.name) + "/secret.json", os.path.join(outside.name, "secret.json")):
            with self.subTest(relative=relative):
                folder.manifest({"A": {"request": relative}})
                with self.assertRaisesRegex(FolderError, "outside the folder"):
                    load_plan(folder.name)

    def test_a_file_that_is_not_a_request_is_refused(self):
        for data in ([], "text", {"method": "POST"}, {"url": "/x"}, {"method": 1, "url": "/x"}):
            with self.subTest(data=data):
                folder = self.folder()
                folder.put("items/A/item.request.json", data)
                folder.manifest({"A": {"request": "items/A/item.request.json"}})
                with self.assertRaisesRegex(FolderError, "is not a request"):
                    load_plan(folder.name)

    def test_a_bom_file_with_a_line_that_is_not_a_request_is_refused(self):
        folder = self.folder()
        folder.manifest({})
        folder.put("bom/A.bom.request.json", {"parent": "A", "requests": ["x"]})
        with self.assertRaisesRegex(FolderError, "is not a request"):
            load_plan(folder.name)

    def test_a_bom_file_of_the_wrong_shape_reads_as_having_no_requests(self):
        folder = self.folder()
        folder.manifest({})
        folder.put("bom/A.bom.request.json", [])
        self.assertEqual(load_plan(folder.name)["boms"], [{"parent": "", "requests": []}])

    def test_an_item_entry_that_is_not_an_object_has_nothing_to_send(self):
        folder = self.folder()
        folder.manifest({"A": "x", "B": None})
        self.assertEqual(load_plan(folder.name)["items"], [])


class SmallTests(unittest.TestCase):
    def test_the_detail_of_a_send_the_cancel_stopped_is_recognised(self):
        self.assertTrue(was_cancelled("Cancelled after 2 request(s)."))
        self.assertFalse(was_cancelled("3 request(s) sent."))

    def test_a_refused_request_keeps_the_status_it_was_refused_with(self):
        class Refusing:
            def send_json(self, method, path, body=None):
                raise FmApiError("refused", 409)

            def with_cancel(self, token):
                return self

        with tempfile.TemporaryDirectory() as root:
            dispatcher = Dispatcher(root, Refusing(), "1")
            with self.assertRaises(FmApiError) as caught:
                dispatcher.send_bom("A", [{"method": "PATCH", "url": "/api/v3/workspaces/1/items/1/bom-items/9", "body": {}}])
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("Request 1 of 1: refused", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

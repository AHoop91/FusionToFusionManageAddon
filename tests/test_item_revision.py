import unittest

from src.fm.bom import RELEASED_BIAS, WORKING_BIAS, BomService
from src.fm.item_search import ItemSearchService
from src.fm.items import ItemService
from src.fm.search_query import WORKING


class _Client:
    def __init__(self, answer=None):
        self.paths, self.answer = [], answer or {"items": [], "totalCount": 0}

    def get_json(self, path, **_):
        self.paths.append(path)
        return self.answer


class ItemRevisionTests(unittest.TestCase):
    def test_a_search_asks_for_the_latest_version_unless_told_otherwise(self):
        client = _Client()
        ItemService(client).search("242", "PN-000701")
        self.assertIn("&revision=1", client.paths[0])

    def test_a_publish_can_ask_for_the_working_version(self):
        client = _Client()
        service = ItemService(client, WORKING)
        service.search("242", "PN-000701")
        service.find_many("242", ["PN-000701"])
        self.assertTrue(all("&revision=3" in path for path in client.paths))


class BomBiasTests(unittest.TestCase):
    NODE = {"nodes": [{"urn": "u1", "title": "A - Top [REV:w]"}], "edges": []}

    def read(self, service):
        client = service._client
        service.read("242", "17073", 1)
        return client.paths[0]

    def test_a_bom_is_read_with_the_released_revision_unless_told_otherwise(self):
        client = _Client(self.NODE)
        self.assertIn("&revisionBias=release&rootId=17073", self.read(BomService(client)))

    def test_a_bom_for_a_publish_is_read_with_the_working_revision(self):
        client = _Client(self.NODE)
        self.assertIn("&revisionBias=working&rootId=17073", self.read(BomService(client, WORKING_BIAS)))


class AddItemsPickerTests(unittest.TestCase):
    def test_the_picker_lists_what_the_working_bom_holds_and_leaves_the_version_toggle_to_the_user(self):
        client = _Client({"nodes": [], "edges": []})
        service = ItemSearchService(client)
        service.members("242", "17073")
        service.page("242", "17073", "", [], 0, 1)
        service.page("242", "17073", "", [], 0, WORKING)
        self.assertIn("&revisionBias=working&rootId=17073", client.paths[0])
        self.assertIn("&revision=1&", client.paths[1])
        self.assertIn("&revision=3&", client.paths[2])


if __name__ == "__main__":
    unittest.main()

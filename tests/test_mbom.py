"""Finding the manufacturing bills of materials of a design by its lineage id and the asset id of its Components record."""

import unittest
from types import SimpleNamespace

from src.fm.client import FmApiError
from src.fm.mbom import ITEM_ASSET_FIELD, ITEM_LINEAGE_FIELD, WORKING_FIELD, MbomService

LINEAGE = "urn:adsk.wipprod:dm.lineage:4A7qrWmaTuG0eOal8ycK3w"
ASSET = "gEDHlC30rZcLLOTVGJMj9m_aga"
LINK = "/api/v3/workspaces/57/items/16997"
RECORD = {"sections": [{"fields": [{"__self__": "/api/v3/workspaces/57/items/16997/views/1/fields/ASSET_URN", "value": ASSET}]}]}


class Client:
    """Answers the v1 search with ``answers`` and the read of the Components record with ``record``."""

    def __init__(self, *answers, record=RECORD):
        self.answers, self.sent, self.record, self.read = list(answers), [], record, []

    def get_json(self, path):
        self.read.append(path)
        return self.record

    def send_json(self, method, path, body=None, content_type="application/json"):
        self.sent.append((method, path, body))
        return SimpleNamespace(status=200, headers={}, data=self.answers.pop(0))


def answer(*items):
    """A v1 answer with a row for each ``(dms id, item number)``; its descriptor is the number and a name."""
    rows = [{"rowId": str(i), "dmsId": dms, "fields": {"entry": [{"key": "NUMBER", "fieldData": {"formattedValue": number}},
                                                                 {"key": ITEM_LINEAGE_FIELD, "fieldData": {"formattedValue": LINEAGE}},
                                                                 {"key": ITEM_ASSET_FIELD, "fieldData": {"formattedValue": ASSET}},
                                                                 {"key": "DESCRIPTOR", "fieldData": {"formattedValue": f"{number} - Name"}}]}}
            for i, (dms, number) in enumerate(items)]
    return {"totalResultCount": len(rows), "row": rows}


class FindTests(unittest.TestCase):
    def test_the_items_made_from_the_design_are_listed_with_their_numbers_and_descriptors(self):
        client = Client(answer(("11", "PN-1-A"), ("12", "PN-1-B")))
        self.assertEqual(MbomService(client).find("242", LINEAGE, LINK, "NUMBER"), [{"id": "11", "number": "PN-1-A", "descriptor": "PN-1-A - Name"},
                                                                                       {"id": "12", "number": "PN-1-B", "descriptor": "PN-1-B - Name"}])

    def test_the_search_is_by_the_lineage_id_and_the_asset_id_together_as_they_are(self):
        client = Client(answer())
        MbomService(client).find("242", LINEAGE, LINK, "NUMBER")
        method, path, body = client.sent[0]
        self.assertEqual((method, path), ("POST", "/api/rest/v1/workspaces/242/items/search"))
        self.assertEqual(body["filter"], [{"fieldID": ITEM_LINEAGE_FIELD, "fieldTypeID": 0, "filterType": {"filterID": 15}, "filterValue": LINEAGE},
                                          {"fieldID": ITEM_ASSET_FIELD, "fieldTypeID": 0, "filterType": {"filterID": 15}, "filterValue": ASSET},
                                          {"fieldID": WORKING_FIELD, "fieldTypeID": 10, "filterType": {"filterID": 13}, "filterValue": ""}])

    def test_the_whole_search_is_sent_as_it_was_proven_live(self):
        client = Client(answer())
        MbomService(client).find("242", LINEAGE, LINK, "NUMBER")
        body = client.sent[0][2]
        self.assertEqual({k: body[k] for k in ("pageNo", "pageSize", "logicClause", "fields", "sort")}, {
            "pageNo": 1, "pageSize": 100, "logicClause": "AND",
            "fields": [{"fieldID": ITEM_LINEAGE_FIELD, "fieldTypeID": 0}, {"fieldID": ITEM_ASSET_FIELD, "fieldTypeID": 0}, {"fieldID": "NUMBER", "fieldTypeID": 0},
                       {"fieldID": "DESCRIPTOR", "fieldTypeID": 15}],
            "sort": [{"fieldID": ITEM_LINEAGE_FIELD, "fieldTypeID": 0, "sortDescending": False}]})

    def test_the_asset_id_is_read_from_the_components_record(self):
        client = Client(answer())
        MbomService(client).find("242", LINEAGE, LINK, "NUMBER")
        self.assertEqual(client.read, [LINK])

    def test_a_record_with_no_asset_id_is_refused_before_a_search(self):
        client = Client(record={"sections": [{"fields": []}]})
        with self.assertRaises(FmApiError):
            MbomService(client).find("242", LINEAGE, LINK, "NUMBER")
        self.assertEqual(client.sent, [])

    def test_a_design_with_no_item_made_from_it_has_an_empty_list(self):
        self.assertEqual(MbomService(Client(answer())).find("242", LINEAGE, LINK, "NUMBER"), [])

    def test_something_that_is_not_a_lineage_id_is_refused_before_anything_is_asked(self):
        client = Client()
        for lineage in ("", "4A7qrWmaTuG0eOal8ycK3w", "urn:adsk.wipprod:dm.lineage:"):
            with self.assertRaises(FmApiError):
                MbomService(client).find("242", lineage, LINK, "NUMBER")
        self.assertEqual((client.sent, client.read), ([], []))

    def test_an_answer_that_is_not_a_search_raises_and_is_not_an_empty_list(self):
        with self.assertRaises(FmApiError):
            MbomService(Client({"error": []})).find("242", LINEAGE, LINK, "NUMBER")


def found(*descriptors):
    """The answer of the v3 search for items with these descriptors."""
    return {"items": [{"__self__": f"/api/v3/workspaces/242/items/{i}", "descriptor": d} for i, d in enumerate(descriptors, 1)]}


class NumberTakenTests(unittest.TestCase):
    def taken(self, *descriptors, number="101-00001-B"):
        client = Client()
        client.get_json = lambda path: found(*descriptors)
        return MbomService(client).number_taken("242", number)

    def test_a_number_an_item_has_is_taken(self):
        self.assertTrue(self.taken("101-00001-B - Reciprocating Saw"))

    def test_the_number_is_compared_whatever_its_case_and_spaces(self):
        self.assertTrue(self.taken("101-00001-b - Saw", number=" 101-00001-B "))

    def test_a_longer_number_that_the_search_also_lists_is_not_the_same_item(self):
        self.assertFalse(self.taken("101-00001-B2 - Other"))

    def test_no_item_leaves_the_number_free(self):
        self.assertFalse(self.taken())

    def test_the_latest_version_of_each_item_is_searched_so_a_released_item_counts(self):
        client = Client()
        asked = []
        client.get_json = lambda path: asked.append(path) or found()
        MbomService(client).number_taken("242", "101-00001-B")
        self.assertIn("revision=1", asked[0])


if __name__ == "__main__":
    unittest.main()

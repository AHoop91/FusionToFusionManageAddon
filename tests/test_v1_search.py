"""The v1 search: the definition that is sent, and the rows that come back."""

import unittest
from types import SimpleNamespace

from src.fm.client import FmApiError
from src.fm.v1_search import (CONTAINS, GRIDVIEW, MAX_PAGES, OR, Field, Filter, Sort, V1SearchService, build_definition, parse_page)


SORT = [Sort("TITLE")]


class Client:
    def __init__(self, *answers, status=200):
        self.answers, self.sent, self.status = list(answers), [], status

    def send_json(self, method, path, body=None, content_type="application/json"):
        self.sent.append((method, path, body))
        return SimpleNamespace(status=self.status, headers={}, data=self.answers.pop(0))


def answer(total, *ids):
    rows = [{"rowId": str(i), "dmsId": dms, "fields": {"entry": [{"key": "TITLE", "fieldData": {"value": f"T{dms}", "formattedValue": f"T{dms}"}}]}}
            for i, dms in enumerate(ids)]
    return {"totalResultCount": total, "columnKey": [{"value": "TITLE", "label": "Title"}], "row": rows}


class DefinitionTests(unittest.TestCase):
    def test_fields_filters_and_sort_are_named_with_their_tab(self):
        body = build_definition([Field("TITLE"), Field("QTY", GRIDVIEW)], [Sort("TITLE", descending=True)],
                                [Filter("TITLE", CONTAINS, "Flash"), Filter("QTY", 15, "1", GRIDVIEW)], page=2, page_size=10)
        self.assertEqual(body["fields"], [{"fieldID": "TITLE", "fieldTypeID": 0}, {"fieldID": "QTY", "fieldTypeID": 2}])
        self.assertEqual(body["filter"][1], {"fieldID": "QTY", "fieldTypeID": 2, "filterType": {"filterID": 15}, "filterValue": "1"})
        self.assertEqual(body["sort"], [{"fieldID": "TITLE", "fieldTypeID": 0, "sortDescending": True}])
        self.assertEqual((body["pageNo"], body["pageSize"], body["logicClause"]), (2, 10, "AND"))

    def test_a_search_with_no_sort_is_refused_before_a_request(self):
        with self.assertRaises(ValueError):
            build_definition([Field("TITLE")], [])

    def test_a_single_filter_is_sent_with_or(self):
        self.assertEqual(build_definition([Field("TITLE")], SORT, [Filter("TITLE", CONTAINS, "x")])["logicClause"], OR)

    def test_a_page_the_service_would_refuse_is_not_sent(self):
        for page, size in ((0, 10), (1, 0), (1, 1000)):
            with self.assertRaises(ValueError):
                build_definition([Field("TITLE")], SORT, page=page, page_size=size)


class NoMatchTests(unittest.TestCase):
    def test_an_answer_with_no_body_is_a_search_that_matched_nothing(self):
        client = Client(None, status=204)
        page = V1SearchService(client).page("5", build_definition([Field("TITLE")], SORT))
        self.assertEqual((page.total, page.rows), (0, []))


class ParseTests(unittest.TestCase):
    def test_rows_hold_the_text_of_each_returned_field(self):
        page = parse_page(answer(14, 234))
        self.assertEqual((page.total, page.rows[0].dms_id, page.rows[0].values), (14, "234", {"TITLE": "T234"}))

    def test_a_picklist_gives_its_label_and_a_blank_field_has_no_entry(self):
        data = {"totalResultCount": 1, "row": [{"dmsId": 5, "fields": {"entry": [{"key": "CAT", "fieldData": {"value": "10", "label": "Top"}}]}}]}
        self.assertEqual(parse_page(data).rows[0].values, {"CAT": "Top"})

    def test_an_answer_that_is_not_a_search_raises(self):
        for data in (None, [], {"reportResult": {"totalResultCount": 1}}):
            with self.assertRaises(FmApiError):
                parse_page(data)


class ServiceTests(unittest.TestCase):
    def test_the_definition_is_posted_to_the_workspace(self):
        client = Client(answer(1, 7))
        page = V1SearchService(client).page("242", {"pageNo": 1})
        self.assertEqual(client.sent, [("POST", "/api/rest/v1/workspaces/242/items/search", {"pageNo": 1})])
        self.assertEqual(page.rows[0].dms_id, "7")

    def test_a_workspace_that_is_not_a_number_is_refused_before_a_request(self):
        client = Client()
        with self.assertRaises(FmApiError):
            V1SearchService(client).page("242/../1", {})
        self.assertEqual(client.sent, [])

    def test_pages_are_read_until_the_total_is_reached(self):
        client = Client(answer(3, 1, 2), answer(3, 3))
        rows = V1SearchService(client).rows("242", [Field("TITLE")], SORT, page_size=2)
        self.assertEqual([r.dms_id for r in rows], ["1", "2", "3"])
        self.assertEqual([body["pageNo"] for _, _, body in client.sent], [1, 2])

    def test_a_search_that_never_ends_raises_and_does_not_return_a_cut_off_list(self):
        client = Client(*[answer(10 ** 6, n) for n in range(1, MAX_PAGES + 1)])
        with self.assertRaises(FmApiError):
            V1SearchService(client).rows("242", [Field("TITLE")], SORT, page_size=1)


if __name__ == "__main__":
    unittest.main()

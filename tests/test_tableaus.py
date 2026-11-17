import unittest

from src.fm.client import FmApiError
from src.fm.tableaus import MAX_VIEW_NAME, META, TableauService, parse_available, parse_columns, parse_rows, parse_titles, parse_views

LIST = "/api/v3/workspaces/242/tableaus"


class _Client:
    """Answers by path, and by path and type where a path is asked for with the META type too."""
    tenant = "acme"

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def send_json(self, method, path, body=None, content_type="application/json"):
        self.sent = getattr(self, "sent", []) + [(method, path, body)]

    def get_json(self, path, accept="application/json"):
        self.asked.append((path, accept))
        answer = self.answers[(path, accept)] if (path, accept) in self.answers else self.answers[path]
        if isinstance(answer, Exception):
            raise answer
        return answer


FILTER_FIELDS = [{"field": {"__self__": "/api/v3/workspaces/242/views/0/fields/DESCRIPTOR", "title": "Item Descriptor"}},
                 {"field": {"__self__": "/api/v3/workspaces/242/views/1/fields/OWNER", "title": "Owner"}}]


class ViewsTests(unittest.TestCase):
    def test_the_views_are_listed_by_id_and_title(self):
        rows = [{"link": "/api/v3/workspaces/242/tableaus/581", "title": "All products"}, {"link": "/api/v3/workspaces/242/tableaus/9", "title": "Mine"}]
        self.assertEqual(parse_views({"tableaus": rows}), [{"id": "581", "name": "All products"}, {"id": "9", "name": "Mine"}])

    def test_views_of_one_name_are_told_apart_by_their_id(self):
        found = parse_views({"tableaus": [{"link": "/x/tableaus/713", "title": "My Default View"}, {"link": "/x/tableaus/714", "title": "My Default View"},
                                          {"link": "/x/tableaus/5", "title": "Other"}]})
        self.assertEqual([v["name"] for v in found], ["My Default View (713)", "My Default View (714)", "Other"])

    def test_an_answer_that_is_not_a_list_has_no_views(self):
        self.assertEqual(parse_views("nope"), [])
        self.assertEqual(parse_views(None), [])


class TitlesTests(unittest.TestCase):
    def test_each_field_is_called_by_the_title_the_filter_list_gives_it(self):
        self.assertEqual(parse_titles(FILTER_FIELDS), {"DESCRIPTOR": "Item Descriptor", "OWNER": "Owner"})

    def test_an_answer_that_is_not_a_list_gives_no_titles(self):
        self.assertEqual(parse_titles({"x": 1}), {})


class RowsTests(unittest.TestCase):
    ITEM = {"link": "/api/v3/workspaces/242/items/10", "urn": "u", "deleted": False}

    def test_fields_named_by_id_become_columns_titled_from_the_filter_list(self):
        data = {"total": 2, "items": [
            {"item": self.ITEM, "fields": [{"id": "DESCRIPTOR", "value": "000001 - Seat"}, {"id": "WF_CURRENT_STATE", "value": "Proposal"}]},
            {"item": {"link": "/api/v3/workspaces/242/items/11"}, "fields": [{"id": "DESCRIPTOR", "value": "000002 - Desk"}]}]}
        found = parse_rows(data, {"DESCRIPTOR": "Item Descriptor"})
        self.assertEqual([(c["id"], c["title"]) for c in found["columns"]], [("DESCRIPTOR", "Item Descriptor"), ("WF_CURRENT_STATE", "WF_CURRENT_STATE")])
        self.assertEqual([r["id"] for r in found["rows"]], ["10", "11"])
        self.assertEqual(found["rows"][0]["cells"], {"DESCRIPTOR": "000001 - Seat", "WF_CURRENT_STATE": "Proposal"})
        self.assertEqual((found["total"], found["raw"]), (2, 2))

    def test_a_picklist_value_is_shown_by_its_title(self):
        found = parse_rows({"items": [{"item": self.ITEM, "fields": [{"id": "OWNER", "value": {"title": "Ann", "link": "x"}}]}]})
        self.assertEqual(found["rows"][0]["cells"], {"OWNER": "Ann"})

    def test_an_answer_with_no_rows_is_an_empty_page(self):
        self.assertEqual(parse_rows(None), {"columns": [], "rows": [], "total": 0, "raw": 0})


DEFINITION = {"columns": [
    {"field": {"__self__": "/api/v3/workspaces/242/views/1/fields/IMAGE", "title": "Image"}, "displayOrder": 1, "allowMultipleFilters": False,
     "applicableFilters": [{"link": "/api/v3/filter-types/22", "name": "Is Blank", "allowValue": False}]},
    {"field": {"__self__": "/api/v3/workspaces/242/views/0/fields/DESCRIPTOR", "title": "Item Descriptor"}, "displayOrder": 0, "allowMultipleFilters": True,
     "applicableFilters": [{"link": "/api/v3/filter-types/2", "name": "Contains", "allowValue": True, "valueType": "STRING"}, {"name": "no link"}]}]}


class ColumnsTests(unittest.TestCase):
    def test_the_columns_come_in_the_order_the_view_shows_them_with_the_filters_each_takes(self):
        found = parse_columns(DEFINITION)
        self.assertEqual([c["id"] for c in found], ["DESCRIPTOR", "IMAGE"])
        self.assertEqual(found[0], {"id": "DESCRIPTOR", "key": "views/0/fields/DESCRIPTOR", "title": "Item Descriptor", "multiple": True,
                                    "filters": [{"id": "/api/v3/filter-types/2", "name": "Contains", "takes_value": True, "kind": "STRING"}],
                                    "applied": {"match": "ALL", "filters": []}})
        self.assertEqual((found[1]["multiple"], found[1]["filters"][0]["takes_value"]), (False, False))

    def test_an_answer_with_no_columns_gives_none(self):
        self.assertEqual(parse_columns({}), [])
        self.assertEqual(parse_columns([]), [])

    def test_the_columns_of_a_view_are_asked_for_with_the_meta_type(self):
        client = _Client({(LIST + "/713", META): DEFINITION})
        found = TableauService(client).columns("242", "713")
        self.assertEqual(client.asked, [(LIST + "/713", META)])
        self.assertEqual(len(found["columns"]), 2)

    def test_a_view_that_is_not_a_number_has_no_columns_asked_for(self):
        client = _Client({})
        with self.assertRaises(FmApiError):
            TableauService(client).columns("242", "../x")
        self.assertEqual(client.asked, [])


class _Made:
    """What a client that makes things answers: a status, headers and no body."""
    def __init__(self, headers):
        self.status, self.headers, self.data = 201, headers, None


class _MakingClient(_Client):
    tenant = "making"

    def __init__(self, answers, refuse_meta=False, headers=None):
        super().__init__(answers)
        self.types = []
        self.refuse_meta = refuse_meta
        self.headers = {"Location": "https://x.example/api/v3/workspaces/57/tableaus/743"} if headers is None else headers

    def send_json(self, method, path, body=None, content_type="application/json"):
        super().send_json(method, path, body)
        self.types.append(content_type)
        if self.refuse_meta and content_type == META:
            raise FmApiError("Unsupported", 415)
        return _Made(self.headers)


OFFERED = [{"field": {"__self__": "/api/v3/workspaces/57/views/0/fields/DESCRIPTOR", "title": "Item Descriptor"}, "group": {"displayName": "Item Descriptor"},
            "allowMultipleFilters": True, "applicableFilters": [{"link": "/api/v3/filter-types/2"}]},
           {"field": {"__self__": "/api/v3/workspaces/57/views/1/fields/OWNER", "title": "Owner"}, "group": {"displayName": "Basic"},
            "allowMultipleFilters": False, "applicableFilters": []}]


class CreateViewTests(unittest.TestCase):
    def client(self, **kwargs):
        return _MakingClient({("/api/v3/workspaces/57/tableaus", META): OFFERED}, **kwargs)

    def create(self, client, name=" Mine ", columns=("views/1/fields/OWNER", "views/0/fields/DESCRIPTOR")):
        return TableauService(client).create_view("57", name, list(columns))

    def test_the_view_is_posted_with_its_columns_in_the_order_chosen_and_its_id_read_from_location(self):
        client = self.client()
        self.assertEqual(self.create(client), {"id": "743"})
        method, path, body = client.sent[0]
        self.assertEqual((method, path, client.types), ("POST", "/api/v3/workspaces/57/tableaus", [META]))
        self.assertEqual((body["name"], body["isDefault"]), ("Mine", False))
        self.assertEqual([(c["field"]["title"], c["displayOrder"], c["visible"]) for c in body["columns"]], [("Owner", 0, True), ("Item Descriptor", 1, True)])
        self.assertEqual(body["columns"][1]["applicableFilters"], [{"link": "/api/v3/filter-types/2"}])

    def test_the_view_is_sorted_by_its_first_column_and_dated_as_fusion_manage_does_it(self):
        client = self.client()
        self.create(client)
        body = client.sent[0][2]
        self.assertEqual(body["columns"][0]["sort"], {"order": 0, "direction": "ASCENDING"})
        self.assertNotIn("sort", body["columns"][1])
        self.assertRegex(body["createdDate"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

    def test_a_column_chosen_twice_is_once(self):
        client = self.client()
        self.create(client, columns=("views/1/fields/OWNER", "views/1/fields/OWNER"))
        self.assertEqual(len(client.sent[0][2]["columns"]), 1)

    def test_a_name_or_columns_that_cannot_be_used_send_nothing(self):
        cases = (("  ", ("views/1/fields/OWNER",)), ("x" * (MAX_VIEW_NAME + 1), ("views/1/fields/OWNER",)), ("Mine", ()), ("Mine", ("views/9/fields/NOPE",)))
        for name, columns in cases:
            with self.subTest(name=name[:5], columns=columns):
                client = self.client()
                with self.assertRaises(FmApiError):
                    self.create(client, name, columns)
                self.assertFalse(getattr(client, "sent", []))

    def test_a_view_the_type_of_which_is_refused_is_an_error(self):
        client = self.client(refuse_meta=True)
        with self.assertRaises(FmApiError):
            self.create(client)
        self.assertEqual(client.types, [META])

    def test_a_refusal_other_than_the_type_is_passed_on(self):
        client = self.client()
        client.send_json = lambda *a, **k: (_ for _ in ()).throw(FmApiError("No", 403))
        with self.assertRaises(FmApiError):
            self.create(client)

    def test_a_view_whose_address_is_not_given_is_an_error(self):
        with self.assertRaises(FmApiError):
            self.create(self.client(headers={}))


class RenameViewTests(unittest.TestCase):
    def client(self):
        import copy
        return _MakingClient({(LIST + "/713", META): copy.deepcopy({**DEFINITION, "name": "Old", "isDefault": False})})

    def test_the_view_is_read_and_put_back_whole_with_only_its_name_changed(self):
        client = self.client()
        self.assertEqual(TableauService(client).rename_view("242", "713", "  New name "), {"id": "713", "name": "New name"})
        method, path, body = client.sent[0]
        self.assertEqual((method, path, client.types), ("PUT", LIST + "/713", [META]))
        self.assertEqual((body["name"], body["isDefault"], len(body["columns"])), ("New name", False, 2))

    def test_a_name_or_view_that_cannot_be_used_sends_nothing(self):
        for view, name in (("713", "  "), ("713", "x" * (MAX_VIEW_NAME + 1)), ("../x", "Fine")):
            with self.subTest(view=view, name=name[:3]):
                client = self.client()
                with self.assertRaises(FmApiError):
                    TableauService(client).rename_view("242", view, name)
                self.assertFalse(getattr(client, "sent", []))


class DeleteViewTests(unittest.TestCase):
    def test_the_view_is_deleted_by_its_address(self):
        client = _MakingClient({})
        self.assertEqual(TableauService(client).delete_view("57", "743"), {"id": "743"})
        self.assertEqual(client.sent, [("DELETE", "/api/v3/workspaces/57/tableaus/743", None)])

    def test_a_view_that_is_not_a_number_is_not_deleted(self):
        client = _MakingClient({})
        for view in ("", "../x", "7/43"):
            with self.subTest(view=view), self.assertRaises(FmApiError):
                TableauService(client).delete_view("57", view)
        self.assertFalse(getattr(client, "sent", []))


class SaveFiltersTests(unittest.TestCase):
    CONTAINS = "/api/v3/filter-types/2"

    def client(self):
        import copy
        return _Client({(LIST + "/713", META): copy.deepcopy(DEFINITION), (LIST, META): []})

    def save(self, client, column="DESCRIPTOR", match="ALL", filters=None):
        change = {"column": column, "match": match, "filters": filters if filters is not None else [{"type": self.CONTAINS, "value": " Airport "}]}
        return TableauService(client).save_view_filters("242", "713", [change])

    def test_the_filters_of_one_column_are_put_into_the_view_and_the_view_saved_whole(self):
        client = self.client()
        self.save(client, match="any")
        method, path, body = client.sent[0]
        self.assertEqual((method, path), ("PUT", LIST + "/713"))
        self.assertEqual(body["columns"][1]["appliedFilters"], {"matchRule": "ANY", "filters": [{"type": self.CONTAINS, "value": "Airport"}]})
        self.assertNotIn("appliedFilters", body["columns"][0])   # the other column is as it was
        self.assertEqual(len(body["columns"]), 2)

    IMAGE, DESCRIPTOR, OWNER = "views/1/fields/IMAGE", "views/0/fields/DESCRIPTOR", "views/1/fields/OWNER"

    def arrange(self, client, columns):
        return TableauService(client).save_view_filters("242", "713", [], columns)

    def test_the_columns_to_show_are_put_in_the_order_given(self):
        client = self.client()
        found = self.arrange(client, [self.IMAGE, self.DESCRIPTOR])
        body = client.sent[0][2]
        self.assertEqual([(c["field"]["title"], c["displayOrder"]) for c in body["columns"]], [("Image", 0), ("Item Descriptor", 1)])
        self.assertEqual([c["id"] for c in found["columns"]], ["IMAGE", "DESCRIPTOR"])

    def test_a_column_left_out_goes_and_one_the_workspace_offers_joins(self):
        client = self.client()
        client.tenant = "arranging"   # what a workspace offers is kept per tenant: not the one the other tests ask about
        client.answers[(LIST, META)] = [{"field": {"__self__": "/api/v3/workspaces/242/views/1/fields/OWNER", "title": "Owner"}, "applicableFilters": []}]
        self.arrange(client, [self.OWNER, self.DESCRIPTOR])
        self.assertEqual([c["field"]["title"] for c in client.sent[0][2]["columns"]], ["Owner", "Item Descriptor"])

    def test_a_view_stays_sorted_when_its_sorted_column_goes(self):
        client = self.client()
        client.answers[(LIST + "/713", META)]["columns"][1]["sort"] = {"order": 0, "direction": "DESCENDING"}   # the descriptor
        self.arrange(client, [self.IMAGE])
        self.assertEqual(client.sent[0][2]["columns"][0]["sort"], {"order": 0, "direction": "ASCENDING"})

    def test_columns_that_cannot_be_shown_save_nothing(self):
        for columns in ([], [self.IMAGE, "views/9/fields/NOPE"], "IMAGE"):
            with self.subTest(columns=columns):
                client = self.client()
                with self.assertRaises(FmApiError):
                    self.arrange(client, columns)
                self.assertFalse(getattr(client, "sent", []))

    def test_the_columns_answered_are_the_ones_saved_without_reading_the_view_again(self):
        client = self.client()
        found = self.save(client)
        self.assertEqual(len(found["columns"]), 2)
        self.assertEqual(sum(1 for _, accept in client.asked if accept == META), 1)

    def test_no_filters_clears_the_column(self):
        client = self.client()
        client.answers[(LIST + "/713", META)]["columns"][1]["appliedFilters"] = {"matchRule": "ALL", "filters": [{"type": self.CONTAINS, "value": "x"}]}
        self.save(client, filters=[])
        self.assertNotIn("appliedFilters", client.sent[0][2]["columns"][1])

    def test_a_filter_the_column_does_not_take_is_refused_and_nothing_is_saved(self):
        for filters in ([{"type": "/api/v3/filter-types/99", "value": "x"}], [{"type": "/x", "value": "x"}], [{"type": self.CONTAINS, "value": " "}]):
            with self.subTest(filters=filters):
                client = self.client()
                with self.assertRaises(FmApiError):
                    self.save(client, filters=filters)
                self.assertFalse(getattr(client, "sent", []))

    def test_a_column_that_takes_one_filter_is_refused_two(self):
        client = self.client()
        with self.assertRaises(FmApiError):
            self.save(client, column="IMAGE", filters=[{"type": "/api/v3/filter-types/22"}, {"type": "/api/v3/filter-types/22"}])

    def test_a_filter_that_takes_no_value_is_saved_without_one(self):
        client = self.client()
        self.save(client, column="IMAGE", filters=[{"type": "/api/v3/filter-types/22", "value": "ignored"}])
        self.assertEqual(client.sent[0][2]["columns"][0]["appliedFilters"]["filters"], [{"type": "/api/v3/filter-types/22"}])

    def test_a_field_the_view_does_not_show_joins_it_as_the_last_column(self):
        client = self.client()
        client.answers[(LIST, META)] = [
            {"field": {"__self__": "/api/v3/workspaces/242/views/1/fields/TITLE", "title": "Title"}, "group": {"displayName": "Product", "displayOrder": 1},
             "allowMultipleFilters": True, "applicableFilters": [{"link": self.CONTAINS, "name": "Contains", "allowValue": True}]}]
        TableauService(client).save_view_filters("242", "713", [{"column": "views/1/fields/TITLE", "match": "ALL", "filters": [{"type": self.CONTAINS, "value": "x"}]}])
        columns = client.sent[0][2]["columns"]
        self.assertEqual(len(columns), 3)
        self.assertEqual((columns[2]["displayOrder"], columns[2]["appliedFilters"]["filters"][0]["value"]), (2, "x"))

    def test_the_fields_on_offer_come_by_section_with_their_filters(self):
        found = parse_available([
            {"field": {"__self__": "/api/v3/workspaces/242/views/1/fields/TITLE", "title": "Title"}, "group": {"displayName": "Product", "displayOrder": 1},
             "allowMultipleFilters": True, "applicableFilters": [{"link": self.CONTAINS, "name": "Contains", "allowValue": True, "valueType": "STRING"}]},
            {"field": {"__self__": "/api/v3/workspaces/242/views/0/fields/DESCRIPTOR", "title": "Item Descriptor"}, "group": {"displayName": "Item Descriptor", "displayOrder": 0}}])
        self.assertEqual([(f["key"], f["group"]) for f in found], [("views/0/fields/DESCRIPTOR", "Item Descriptor"), ("views/1/fields/TITLE", "Product")])
        self.assertEqual(found[1]["filters"][0]["name"], "Contains")

    def test_several_columns_are_saved_in_one_put_or_none_at_all(self):
        client = self.client()
        TableauService(client).save_view_filters("242", "713", [
            {"column": "DESCRIPTOR", "match": "ALL", "filters": [{"type": self.CONTAINS, "value": "a"}]},
            {"column": "IMAGE", "match": "ALL", "filters": [{"type": "/api/v3/filter-types/22"}]}])
        self.assertEqual(len(client.sent), 1)
        self.assertIn("appliedFilters", client.sent[0][2]["columns"][0])
        self.assertIn("appliedFilters", client.sent[0][2]["columns"][1])
        client = self.client()
        with self.assertRaises(FmApiError):
            TableauService(client).save_view_filters("242", "713", [
                {"column": "DESCRIPTOR", "match": "ALL", "filters": [{"type": self.CONTAINS, "value": "a"}]},
                {"column": "NOPE", "match": "ALL", "filters": []}])
        self.assertFalse(getattr(client, "sent", []))

    def test_an_unknown_column_or_match_rule_or_view_is_refused(self):
        for kwargs in ({"column": "NOPE"}, {"match": "SOME"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FmApiError):
                self.save(self.client(), **kwargs)
        with self.assertRaises(FmApiError):
            TableauService(self.client()).save_view_filters("242", "../x", [])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        TableauService._meta.clear()

    def test_the_views_are_read_and_the_field_titles_asked_for(self):
        client = _Client({LIST: [{"link": "/x/tableaus/5", "title": "A"}], (LIST, META): FILTER_FIELDS})
        self.assertEqual(TableauService(client).views("242"), {"views": [{"id": "5", "name": "A"}]})
        self.assertEqual(client.asked[1], (LIST, META))

    def test_field_titles_that_cannot_be_read_fail_the_views_and_the_rows(self):
        client = _Client({LIST: [{"link": "/x/tableaus/5", "title": "A"}], (LIST, META): FmApiError("no", 406),
                          LIST + "/5": {}, LIST + "/5?page=1&size=50": {"items": []}})
        service = TableauService(client)
        with self.assertRaises(FmApiError):
            service.views("242")
        with self.assertRaises(FmApiError):
            service.rows("242", "5", 1, 50)

    def test_a_page_of_a_view_is_asked_for_by_page_and_size_with_the_columns_titled(self):
        client = _Client({LIST + "/581": {}, LIST + "/581?page=2&size=50": {"items": [{"item": {"link": "/i/items/1"}, "fields": [{"id": "OWNER", "value": "Ann"}]}]},
                          (LIST, META): FILTER_FIELDS})
        found = TableauService(client).rows("242", "581", 2, 50)
        self.assertEqual((found["page"], found["size"]), (2, 50))
        self.assertEqual(found["columns"], [{"id": "OWNER", "title": "Owner", "kind": "text"}])

    def test_the_field_titles_are_read_once_for_the_pages_of_a_view(self):
        client = _Client({LIST + "/581": {}, LIST + "/581?page=1&size=50": {}, LIST + "/581?page=2&size=50": {}, (LIST, META): FILTER_FIELDS})
        service = TableauService(client)
        service.rows("242", "581", 1, 50)
        service.rows("242", "581", 2, 50)
        self.assertEqual(sum(1 for _, accept in client.asked if accept == META), 1)

    def test_the_page_and_the_size_are_kept_in_range(self):
        client = _Client({LIST + "/581": {}, LIST + "/581?page=1&size=200": {}, (LIST, META): []})
        found = TableauService(client).rows("242", "581", -4, 99999)
        self.assertEqual((found["page"], found["size"]), (1, 200))

    def test_a_view_that_is_not_a_number_is_not_asked_for(self):
        client = _Client({})
        with self.assertRaises(FmApiError):
            TableauService(client).rows("242", "../x", 1, 50)
        self.assertEqual(client.asked, [])


if __name__ == "__main__":
    unittest.main()


class PictureAndMarkupTests(unittest.TestCase):
    def test_a_formula_that_holds_escaped_markup_gives_its_markup_and_a_plain_text(self):
        found = parse_rows({"items": [{"item": {"link": "/api/v3/workspaces/1/items/9"},
                                       "fields": [{"id": "PRIORITY", "value": "&lt;span style=&quot;color:#fff&quot;&gt;■■■&lt;/span&gt;"}]}]})
        row = found["rows"][0]
        self.assertEqual(row["html"], {"PRIORITY": '<span style="color:#fff">■■■</span>'})
        self.assertEqual(row["cells"]["PRIORITY"], "■■■")

    def test_an_image_column_is_marked_and_a_plain_cell_has_no_markup(self):
        found = parse_rows({"items": [{"item": {"link": "/api/v3/workspaces/1/items/9"},
                                       "fields": [{"id": "IMAGE", "value": "1283", "type": {"title": "Image"}}, {"id": "NAME", "value": "Seat"}]}]})
        self.assertEqual([(c["id"], c["kind"]) for c in found["columns"]], [("IMAGE", "image"), ("NAME", "text")])
        self.assertEqual(found["rows"][0]["html"], {})

    def test_a_picture_number_gives_the_link_without_reading_the_item(self):
        client = _Client({})
        asked = []
        client.get_bytes = lambda link: (asked.append(link), (b"PNG", "image/png"))[1]
        found = TableauService(client).image("242", "9", "IMAGE", "1283")
        self.assertEqual(found, {"image": "data:image/png;base64,UE5H"})
        self.assertEqual(asked, ["/api/v2/workspaces/242/items/9/field-values/IMAGE/image/1283"])
        with self.assertRaises(FmApiError):
            TableauService(client).image("242", "9", "IMAGE", "../x")

    def test_a_picture_without_a_number_is_an_error(self):
        with self.assertRaises(FmApiError):
            TableauService(_Client({})).image("242", "9", "IMAGE", "")

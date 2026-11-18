"""The products of Portfolio Management: creating one, and the actions of the Assign Product panel."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.config.workspace_models import PORTFOLIO_KIND, VariantsConfig, WorkspaceConfig
from src.fm.client import FmApiError, SendResult
from src.fm.components import Candidate
from src.publish import products
from src.publish.products import ProductService
from src.ui.item_number_error import NoItemNumber
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui.actions import product_actions
    from src.ui.actions.product_actions import ProductReads
    from src.ui.message_bridge import MessageBridge
    from src.ui.product_mode import BROWSE, PRODUCT_MODE, USAGE


CONTEXTS = SimpleNamespace(attempt=lambda: (SimpleNamespace(stamp="stamp-1"), ""))   # the hub context the Item panel's tabs are asked under


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()
        self.sections = mock.Mock()
        self.sections.return_value.field_sections.return_value = {"TITLE": "/api/v3/workspaces/77/sections/5",
                                                                  "STATUS": "/api/v3/workspaces/77/sections/6"}
        patcher = mock.patch.object(products, "SectionService", self.sections)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_product_is_created_with_the_values_in_their_sections_and_answered_with_its_id(self):
        self.client.send_json.return_value = SendResult(201, {"Location": "/api/v3/workspaces/77/items/901"}, None)
        row = ProductService(self.client).create("77", {"TITLE": "Airport Seat", "STATUS": "/api/v3/lookups/STATES/options/2", "EMPTY": ""})
        method, url, body = self.client.send_json.call_args[0]
        self.assertEqual((method, url), ("POST", "/api/v3/workspaces/77/items"))
        sent = {f["__self__"].rsplit("/", 1)[1]: f["value"] for s in body["sections"] for f in s["fields"]}
        self.assertEqual(sent, {"TITLE": "Airport Seat", "STATUS": {"link": "/api/v3/lookups/STATES/options/2"}})
        self.assertEqual((row["id"], row["link"]), ("901", "/api/v3/workspaces/77/items/901"))

    def test_a_field_no_section_holds_says_so_instead_of_sending(self):
        with self.assertRaises(FmApiError):
            ProductService(self.client).create("77", {"UNKNOWN": "x"})
        self.client.send_json.assert_not_called()

    def test_a_refusal_that_names_fields_is_read_for_the_form(self):
        body = '{"message": "Validation failed", "errors": [{"field": "TITLE", "message": "Title is required"}]}'
        self.client.send_json.side_effect = FmApiError("HTTP 400", 400, body)
        with self.assertRaises(FmApiError) as raised:
            ProductService(self.client).create("77", {"TITLE": "x"})
        self.assertEqual((str(raised.exception), raised.exception.fields), ("Validation failed", {"TITLE": "Title is required"}))

    def test_what_fusion_manage_refuses_with_is_passed_on(self):
        self.client.send_json.side_effect = FmApiError("Required field 'OWNER' is missing", 400)
        with self.assertRaises(FmApiError) as raised:
            ProductService(self.client).create("77", {"TITLE": "Airport Seat"})
        self.assertIn("OWNER", str(raised.exception))


class EditTests(unittest.TestCase):
    OPTION = "/api/v3/lookups/STATES/options/2"

    def setUp(self):
        self.client = mock.Mock()
        self.items = mock.Mock()
        self.items.return_value.read.return_value = {"TITLE": "Airport Seat", "STATUS": {"link": self.OPTION, "title": "Active"},
                                                     "OWNERS": [{"link": "/u/1", "title": "A"}, {"link": "/u/2", "title": "B"}]}
        self.sections = mock.Mock()
        self.sections.return_value.field_sections.return_value = {"TITLE": "/api/v3/workspaces/77/sections/5",
                                                                  "STATUS": "/api/v3/workspaces/77/sections/6",
                                                                  "OWNERS": "/api/v3/workspaces/77/sections/6"}
        for patcher in (mock.patch.object(products, "SectionService", self.sections), mock.patch.object(products, "ItemService", self.items)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_what_differs_is_sent_to_the_item(self):
        self.client.send_json.return_value = SendResult(200, {}, None)
        row = ProductService(self.client).update("77", "901", {"TITLE": "Airport Chair", "STATUS": self.OPTION,
                                                               "OWNERS": [{"link": "/u/2"}, {"link": "/u/1"}]})
        method, url, body = self.client.send_json.call_args[0]
        self.assertEqual((method, url), ("PATCH", "/api/v3/workspaces/77/items/901"))
        sent = {f["__self__"].rsplit("/", 1)[1]: f["value"] for s in body["sections"] for f in s["fields"]}
        self.assertEqual(sent, {"TITLE": "Airport Chair"})
        self.assertEqual((row["id"], row["unchanged"]), ("901", False))

    def test_nothing_is_sent_when_nothing_changed(self):
        row = ProductService(self.client).update("77", "901", {"TITLE": "Airport Seat", "STATUS": self.OPTION})
        self.client.send_json.assert_not_called()
        self.assertTrue(row["unchanged"])

    def test_a_refusal_is_read_for_the_form(self):
        body = '{"message": "Validation failed", "errors": [{"field": "TITLE", "message": "Too long"}]}'
        self.client.send_json.side_effect = FmApiError("HTTP 400", 400, body)
        with self.assertRaises(FmApiError) as raised:
            ProductService(self.client).update("77", "901", {"TITLE": "x"})
        self.assertEqual(raised.exception.fields, {"TITLE": "Too long"})

    def test_the_values_of_a_product_are_read_from_its_item(self):
        self.assertEqual(ProductService(self.client).read("77", "901")["TITLE"], "Airport Seat")
        self.items.return_value.read.assert_called_once_with("77", "901")


class AssignTests(unittest.TestCase):
    LINK = "/api/v3/lookups/COMPONENTS/options/5"

    def setUp(self):
        self.client = mock.Mock()
        self.workspace = mock.Mock()
        self.workspace.return_value.fields.return_value = ([{"id": "PRIMARY", "link_lookup": "COMPONENTS"}], "")
        self.workspace.return_value.grid_fields.return_value = ([{"id": "VARIANT", "link_lookup": "COMPONENTS"}], "")
        self.components = mock.Mock()
        self.components.return_value.matching.return_value = ([Candidate(self.LINK, "PN-1 - Axle", "[REV:w]")], "")
        self.items = mock.Mock()
        self.sections = mock.Mock()
        self.sections.return_value.field_sections.return_value = {"PRIMARY": "/api/v3/workspaces/77/sections/5"}
        self.client.send_json.return_value = SendResult(200, {}, None)
        for patcher in (mock.patch.object(products, "WorkspaceService", self.workspace), mock.patch.object(products, "ComponentService", self.components),
                        mock.patch.object(products, "ItemService", self.items), mock.patch.object(products, "SectionService", self.sections)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def held(self, value):
        self.items.return_value.read.return_value = {"PRIMARY": value}
        self.items.return_value.read_named.return_value = ("24-1 - Gearbox", {"PRIMARY": value})

    def assign(self, mode=""):
        return ProductService(self.client).assign("77", "901", "PN-1", "PRIMARY", "VARIANT", mode)

    def test_a_product_without_a_primary_component_gets_it_by_a_patch_of_that_field(self):
        self.held(None)
        answer = self.assign()
        method, url, body = self.client.send_json.call_args[0]
        self.assertEqual((answer["status"], method, url), ("assigned", "PATCH", "/api/v3/workspaces/77/items/901"))
        sent = {f["__self__"].rsplit("/", 1)[1]: f["value"] for s in body["sections"] for f in s["fields"]}
        self.assertEqual(sent, {"PRIMARY": {"link": self.LINK}})
        self.components.return_value.matching.assert_called_once_with("COMPONENTS", "PN-1")

    def test_a_product_that_has_one_already_is_asked_about_and_nothing_is_sent(self):
        self.held({"link": "/api/v3/workspaces/9/items/1", "title": "PN-0 - Old"})
        answer = self.assign()
        self.assertEqual((answer["status"], answer["current"], answer["number"], answer["product"]), ("exists", "PN-0 - Old", "PN-1", "24-1 - Gearbox"))
        self.client.send_json.assert_not_called()

    def test_the_component_that_is_the_primary_one_already_changes_nothing(self):
        self.held({"link": self.LINK, "title": "PN-1 - Axle"})
        self.assertEqual(self.assign()["status"], "same")
        self.client.send_json.assert_not_called()

    def test_replacing_changes_the_field(self):
        self.held({"link": "/api/v3/workspaces/9/items/1", "title": "PN-0 - Old"})
        self.assertEqual(self.assign("replace")["status"], "assigned")
        self.assertEqual(self.client.send_json.call_args[0][0], "PATCH")

    def test_adding_a_variant_posts_a_grid_row_linking_the_component(self):
        self.held({"link": "/api/v3/workspaces/9/items/1", "title": "PN-0 - Old"})
        self.assertEqual(self.assign("variant")["status"], "variant")
        method, url, body = self.client.send_json.call_args[0]
        self.assertEqual((method, url), ("POST", "/api/v3/workspaces/77/items/901/views/13/rows"))
        self.assertEqual(body, {"rowData": [{"__self__": "/api/v3/workspaces/77/views/13/fields/VARIANT", "value": {"link": self.LINK}}]})

    def test_replacing_and_keeping_adds_the_old_component_as_a_variant_before_the_change(self):
        old = "/api/v3/workspaces/9/items/1"
        self.held({"link": old, "title": "PN-0 - Old"})
        self.assertEqual(self.assign("replace_move")["status"], "assigned")
        calls = [c[0] for c in self.client.send_json.call_args_list]
        self.assertEqual([(m, u) for m, u, _ in calls], [("POST", "/api/v3/workspaces/77/items/901/views/13/rows"), ("PATCH", "/api/v3/workspaces/77/items/901")])
        self.assertEqual(calls[0][2]["rowData"][0]["value"], {"link": old})

    def test_the_other_columns_of_the_row_are_sent_with_it_and_a_blank_is_not(self):
        self.held({"link": "/api/v3/workspaces/9/items/1", "title": "PN-0 - Old"})
        values = {"QTY": "3", "TYPE": "/api/v3/lookups/8/options/2", "NOTE": "", "VARIANT": "ignored"}
        ProductService(self.client).assign("77", "901", "PN-1", "PRIMARY", "VARIANT", "variant", values)
        cells = {c["__self__"].rsplit("/", 1)[1]: c["value"] for c in self.client.send_json.call_args[0][2]["rowData"]}
        self.assertEqual(cells, {"VARIANT": {"link": self.LINK}, "QTY": "3", "TYPE": {"link": "/api/v3/lookups/8/options/2"}})

    GRID = {"rows": [
        {"__self__": "/api/v3/workspaces/77/items/901/views/13/rows/1", "rowData": [
            {"__self__": "/api/v3/workspaces/77/views/13/fields/VARIANT", "value": {"link": "/api/v3/lookups/COMPONENTS/options/5", "title": "PN-1 - Axle"}},
            {"__self__": "/api/v3/workspaces/77/views/13/fields/QTY", "value": 2}]},
        {"__self__": "/api/v3/workspaces/77/items/901/views/13/rows/2", "rowData": [
            {"__self__": "/api/v3/workspaces/77/views/13/fields/VARIANT", "value": {"link": "/api/v3/lookups/COMPONENTS/options/4", "title": "PN-1 - Axle"}}]},
        {"__self__": "/api/v3/workspaces/77/items/901/views/13/rows/3", "rowData": [
            {"__self__": "/api/v3/workspaces/77/views/13/fields/VARIANT", "value": {"link": "/api/v3/lookups/COMPONENTS/options/8", "title": "PN-9 - Gear"}}]}]}

    def test_inspect_says_how_the_primary_component_and_each_grid_row_stand_to_the_component(self):
        self.held({"link": "/api/v3/lookups/COMPONENTS/options/4", "title": "PN-1 - Axle"})
        self.client.get_json.return_value = self.GRID
        self.workspace.return_value.grid_fields.return_value = ([{"id": "VARIANT", "title": "Variant", "link_lookup": "COMPONENTS", "order": 1, "shown": True},
                                                                 {"id": "QTY", "title": "Quantity", "link_lookup": "", "order": 2, "shown": True}], "")
        info = ProductService(self.client).inspect("77", "901", "PN-1", "PRIMARY", "VARIANT")
        self.assertEqual((info["product"], info["primary_state"], info["component"]), ("24-1 - Gearbox", "revision", self.LINK))
        self.assertEqual([r["state"] for r in info["rows"]], ["same", "revision", "other"])
        self.assertEqual(info["rows"][0]["cells"], {"VARIANT": "PN-1 - Axle", "QTY": "2"})
        self.assertEqual([c["title"] for c in info["columns"]], ["Variant", "Quantity"])

    def test_contents_lists_the_primary_component_and_the_rows_of_the_grid_with_no_design(self):
        self.held({"link": "/api/v3/workspaces/9/items/4", "title": "PN-1 - Axle"})
        self.client.get_json.return_value = self.GRID
        self.workspace.return_value.grid_fields.return_value = ([{"id": "VARIANT", "title": "Variant", "link_lookup": "COMPONENTS", "order": 1, "shown": True},
                                                                 {"id": "QTY", "title": "Quantity", "link_lookup": "", "order": 2, "shown": True}], "")
        info = ProductService(self.client).contents("77", "901", "PRIMARY", "VARIANT")
        self.assertEqual((info["product"], info["primary"]), ("24-1 - Gearbox", {"link": "/api/v3/workspaces/9/items/4", "title": "PN-1 - Axle"}))
        self.assertEqual([(r["title"], r["link"]) for r in info["rows"]], [("PN-1 - Axle", "/api/v3/lookups/COMPONENTS/options/5"),
                                                                       ("PN-1 - Axle", "/api/v3/lookups/COMPONENTS/options/4"),
                                                                       ("PN-9 - Gear", "/api/v3/lookups/COMPONENTS/options/8")])
        self.assertEqual(info["rows"][0]["cells"], {"VARIANT": "PN-1 - Axle", "QTY": "2"})

    def test_a_row_of_the_grid_has_the_page_in_fusion_manage_of_the_component_it_names(self):
        self.held(None)
        self.client.base_url, self.client.tenant = "https://acme.autodeskplm360.net", "ACME"
        self.client.get_json.return_value = {"rows": [
            {"__self__": "/api/v3/workspaces/77/items/901/views/13/rows/1", "rowData": [
                {"__self__": "/api/v3/workspaces/77/views/13/fields/VARIANT", "value": {"link": "/api/v3/workspaces/57/items/9", "title": "PN-1 - Axle"}}]}]}
        self.workspace.return_value.grid_fields.return_value = ([{"id": "VARIANT", "title": "Variant", "link_lookup": "COMPONENTS", "order": 1, "shown": True}], "")
        row = ProductService(self.client).contents("77", "901", "PRIMARY", "VARIANT")["rows"][0]
        self.assertEqual((row["link"], row["title"]), ("/api/v3/workspaces/57/items/9", "PN-1 - Axle"))
        self.assertTrue(row["url"].startswith("https://acme.autodeskplm360.net/plm/workspaces/57/items/itemDetails"))

    def test_the_id_of_a_row_is_not_a_column_of_the_grid(self):
        self.held(None)
        self.client.get_json.return_value = {"rows": [{"__self__": "/api/v3/workspaces/77/items/901/views/13/rows/5", "rowData": [
            {"__self__": "/api/v3/workspaces/77/items/901/views/13/rows/5", "title": "Row Id", "value": 5},
            {"__self__": "/api/v3/workspaces/77/views/13/fields/SKU", "title": "SKU", "value": "A-1"}]}]}
        self.workspace.return_value.grid_fields.return_value = ([{"id": "SKU", "title": "SKU", "order": 1, "shown": True}], "")
        info = ProductService(self.client).contents("77", "901", "PRIMARY", "")
        self.assertEqual(([c["title"] for c in info["columns"]], info["rows"][0]["cells"]), (["SKU"], {"SKU": "A-1"}))

    def test_the_columns_of_the_grid_are_in_the_order_fusion_manage_lays_them_out_whatever_the_rows_hold(self):
        self.held(None)
        self.client.get_json.return_value = {"rows": []}
        self.workspace.return_value.grid_fields.return_value = ([
            {"id": "BOM", "title": "BOM", "order": 5, "shown": True}, {"id": "TITLE", "title": "Title", "order": 1, "shown": True},
            {"id": "HIDDEN", "title": "Hidden", "order": 2, "shown": False}, {"id": "REGION", "title": "Region", "order": 3, "shown": True}], "")
        info = ProductService(self.client).contents("77", "901", "PRIMARY", "BOM")
        self.assertEqual([c["title"] for c in info["columns"]], ["Title", "Region", "BOM"])

    def test_contents_says_there_is_no_primary_component_and_names_no_component_when_the_column_is_not_set_up(self):
        self.held(None)
        self.client.get_json.return_value = self.GRID
        self.workspace.return_value.grid_fields.return_value = ([{"id": "VARIANT", "title": "Variant", "link_lookup": "COMPONENTS", "order": 1, "shown": True}, {"id": "QTY", "title": "Quantity", "link_lookup": "", "order": 2, "shown": True}], "")
        info = ProductService(self.client).contents("77", "901", "PRIMARY", "")
        self.assertEqual(info["primary"], None)
        self.assertEqual([r["link"] for r in info["rows"]], ["", "", ""])
        self.assertEqual(info["rows"][0]["cells"]["QTY"], "2")

    def test_a_row_of_another_revision_is_changed_by_a_put_to_that_row(self):
        self.assertEqual(ProductService(self.client).update_variant("77", "901", "2", "PN-1", "VARIANT")["status"], "updated")
        method, url, body = self.client.send_json.call_args[0]
        self.assertEqual((method, url), ("PUT", "/api/v3/workspaces/77/items/901/views/13/rows/2"))
        self.assertEqual(body["rowData"][0]["value"], {"link": self.LINK})

    def test_a_refusal_of_a_row_is_said_in_words_and_not_sent_again(self):
        refused = FmApiError("400", 400, '{"errorCode": "GEN_INVALID_INPUT_SCHEMA", "message": "Incorrect payload"}')
        self.held({"link": "/api/v3/workspaces/9/items/1", "title": "PN-0 - Old"})
        self.client.send_json.side_effect = [refused]
        with self.assertRaises(FmApiError) as caught:
            self.assign("variant")
        self.assertIn("Incorrect payload", str(caught.exception))
        self.assertNotEqual(caught.exception.status, 400)
        self.assertEqual(self.client.send_json.call_count, 1)

    FIVE = [Candidate("/o/15677", "PN-1 - Axle", "[REV:s1]"), Candidate("/o/15722", "PN-1 - Axle", "[REV:C]"),
            Candidate("/o/15695", "PN-1 - Axle", "[REV:sB]"), Candidate("/o/15745", "PN-1 - Axle", "[REV:w]")]

    def assign_among(self, options):
        self.components.return_value.matching.return_value = (options, "")
        self.held(None)
        return self.assign()

    def test_the_latest_released_revision_is_assigned_not_the_working_version(self):
        answer = self.assign_among(self.FIVE)
        self.assertEqual((answer["status"], answer["component"]), ("assigned", "/o/15722"))
        sent = self.client.send_json.call_args[0][2]["sections"][0]["fields"][0]["value"]
        self.assertEqual(sent, {"link": "/o/15722"})

    def test_the_latest_is_the_one_with_the_largest_id_whatever_the_order_listed(self):
        for options in (self.FIVE, list(reversed(self.FIVE))):
            with self.subTest(first=options[0].link):
                self.assertEqual(self.assign_among(options)["component"], "/o/15722")

    def test_the_working_version_is_assigned_when_there_is_no_released_revision(self):
        answer = self.assign_among([Candidate("/o/15745", "PN-1 - Axle", "[REV:w]")])
        self.assertEqual((answer["status"], answer["component"]), ("assigned", "/o/15745"))

    def test_a_variant_takes_the_same_revision_from_the_columns_own_picklist(self):
        self.workspace.return_value.grid_fields.return_value = ([{"id": "VARIANT", "link_lookup": "OTHER"}], "")
        self.components.return_value.matching.side_effect = [
            ([Candidate("/o/1", "PN-1 - Axle", "[REV:w]")], ""), ([Candidate("/g/9", "PN-1 - Axle", "[REV:w]"), Candidate("/g/8", "PN-1 - Axle", "[REV:A]")], "")]
        self.held({"link": "/api/v3/workspaces/9/items/1", "title": "PN-0"})
        self.assign("variant")
        body = self.client.send_json.call_args[0][2]
        self.assertEqual(body["rowData"][0]["value"], {"link": "/g/9"})

    def test_a_component_that_cannot_be_found_says_why(self):
        self.components.return_value.matching.return_value = ([], "No component PN-1.")
        with self.assertRaises(FmApiError) as caught:
            self.assign()
        self.assertEqual(str(caught.exception), "No component PN-1.")
        self.client.send_json.assert_not_called()

    def test_a_field_that_no_longer_links_to_components_is_said_so(self):
        self.workspace.return_value.fields.return_value = ([{"id": "PRIMARY", "link_lookup": ""}], "")
        with self.assertRaises(FmApiError):
            self.assign()


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(config=SimpleNamespace(workspaces={PORTFOLIO_KIND: WorkspaceConfig(workspace_id="77")}),
                                      effective_settings=lambda: object())
        self.queued = []
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, contexts=CONTEXTS)
        self.service = mock.Mock()
        self.tableaus = mock.Mock()
        self.form = mock.Mock()
        for patcher in (mock.patch.object(product_actions, "ProductService", self.service),
                        mock.patch.object(product_actions, "WorkspaceFormService", self.form),
                        mock.patch.object(product_actions, "TableauService", self.tableaus),
                        mock.patch.object(product_actions, "may", return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def finish(self):
        while self.queued:
            self.queued.pop(0)()

    def test_the_views_are_read_for_the_portfolio_workspace(self):
        self.tableaus.return_value.views.return_value = {"views": []}
        self.reads.views({"token": "t1"})
        self.finish()
        self.tableaus.return_value.views.assert_called_once_with("77")
        self.assertTrue(self.reads.status({"token": "t1"})["ok"])

    def test_a_view_is_created_in_the_portfolio_workspace_with_the_name_and_columns(self):
        self.tableaus.return_value.create_view.return_value = {"id": "743"}
        self.reads.create_view({"token": "t1", "name": "Mine", "columns": ["views/0/fields/DESCRIPTOR"]})
        self.finish()
        self.tableaus.return_value.create_view.assert_called_once_with("77", "Mine", ["views/0/fields/DESCRIPTOR"])
        self.assertEqual(self.reads.status({"token": "t1"})["result"], {"id": "743"})

    def test_a_view_is_renamed_in_the_portfolio_workspace(self):
        self.reads.rename_view({"token": "t1", "view": "743", "name": "Mine"})
        self.finish()
        self.tableaus.return_value.rename_view.assert_called_once_with("77", "743", "Mine")

    def test_a_view_is_deleted_in_the_portfolio_workspace(self):
        self.reads.delete_view({"token": "t1", "view": "743"})
        self.finish()
        self.tableaus.return_value.delete_view.assert_called_once_with("77", "743")

    def test_a_page_of_a_view_is_read(self):
        self.reads.rows({"token": "t1", "view": "581", "page": 2, "size": 50})
        self.finish()
        self.tableaus.return_value.rows.assert_called_once_with("77", "581", 2, 50)

    def test_a_product_is_created_from_the_values_filled_in(self):
        self.service.return_value.create.return_value = {"id": "9"}
        self.reads.create({"token": "t1", "values": {"TITLE": "Seat", "COUNT": 3}})
        self.finish()
        self.service.return_value.create.assert_called_once_with("77", {"TITLE": "Seat", "COUNT": 3})

    def test_the_views_say_whether_a_product_can_be_created(self):
        self.tableaus.return_value.views.return_value = {"views": []}
        for allowed in (True, False):
            with self.subTest(allowed=allowed), mock.patch.object(product_actions, "may", return_value=allowed) as may:
                self.reads.views({"token": "v%s" % allowed})
                self.finish()
                may.assert_called_once_with(mock.ANY, "77", "add_items")
                self.assertEqual(self.reads.status({"token": "v%s" % allowed})["result"]["can_create"], allowed)

    def test_nothing_is_read_when_portfolio_management_is_off(self):
        self.config.config.workspaces[PORTFOLIO_KIND].enabled = False
        answer = self.reads.views({"token": "t1"})
        self.assertEqual((answer["ok"], answer["pending"], answer["message"]), (False, False, "Product Portfolio Management is turned off in the settings."))
        self.assertEqual(self.queued, [])

    def test_a_config_without_the_setting_is_enabled(self):
        self.assertTrue(WorkspaceConfig.from_dict({"workspace_id": "1"}).enabled)
        self.assertFalse(WorkspaceConfig.from_dict(WorkspaceConfig(enabled=False).to_dict()).enabled)

    def test_a_product_is_read_and_updated_for_the_portfolio_workspace(self):
        self.reads.item({"token": "t1", "item": "901"})
        self.reads.update({"token": "t2", "item": "901", "values": {"TITLE": "Seat"}})
        self.finish()
        self.service.return_value.read.assert_called_once_with("77", "901")
        self.service.return_value.update.assert_called_once_with("77", "901", {"TITLE": "Seat"})

    def test_a_picture_is_read_from_the_link_the_item_gave_and_alongside_the_other_reads(self):
        self.reads.picture({"token": "t1", "link": "/api/v2/workspaces/77/items/9/field-values/IMAGE/image/12"})
        self.reads.image({"token": "t2", "item": "9", "field": "IMAGE"})
        self.assertEqual(len(self.queued), 2)
        self.finish()
        self.tableaus.return_value.picture.assert_called_once_with("77", "/api/v2/workspaces/77/items/9/field-values/IMAGE/image/12")

    def test_an_update_needs_the_item_and_a_value(self):
        for payload in ({"item": "", "values": {"A": "x"}}, {"item": "9", "values": {"A": "  "}}, {"item": "9"}):
            with self.subTest(payload=payload):
                answer = self.reads.update(dict(payload, token="t1"))
                self.assertEqual((answer["ok"], answer["pending"]), (False, False))
        self.assertEqual(self.queued, [])

    def test_a_form_with_nothing_filled_in_creates_nothing(self):
        for values in ({}, {"TITLE": "   "}, "not an object", None):
            with self.subTest(values=values):
                answer = self.reads.create({"token": "t1", "values": values})
                self.assertEqual((answer["ok"], answer["pending"], answer["message"]), (False, False, "Fill in at least one field."))
        self.assertEqual(self.queued, [])

    def test_the_fields_a_refusal_names_reach_the_panel_with_the_answer(self):
        from src.fm.refusal import FmRefused
        self.service.return_value.create.side_effect = FmRefused("Validation failed", 400, {"TITLE": "Title is required"})
        self.reads.create({"token": "t1", "values": {"TITLE": "x"}})
        self.finish()
        done = self.reads.status({"token": "t1"})
        self.assertEqual((done["ok"], done["message"], done["fields"]), (False, "Validation failed", {"TITLE": "Title is required"}))

    def test_the_form_is_read_for_the_portfolio_workspace(self):
        self.form.return_value.form.return_value = {"sections": []}
        self.reads.form({"token": "t1"})
        self.finish()
        self.form.return_value.form.assert_called_once_with("77", set())

    def test_the_primary_component_field_is_asked_for_as_filled_in_by_the_add_in(self):
        self.config.config.workspaces[PORTFOLIO_KIND].component_field = "PRIMARY"
        self.form.return_value.form.return_value = {"sections": []}
        self.reads.form({"token": "t1"})
        self.finish()
        self.form.return_value.form.assert_called_once_with("77", {"PRIMARY"})

    def test_assign_asks_the_open_design_for_its_number_and_gives_the_settings_fields(self):
        cfg = self.config.config.workspaces[PORTFOLIO_KIND]
        cfg.component_field, cfg.variants.link_column = "PRIMARY", "VARIANT"
        design = mock.Mock()
        design.number.return_value = "PN-1"
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        self.service.return_value.assign.return_value = {"status": "assigned"}
        self.reads.assign({"token": "t1", "item": "9", "mode": "variant"})
        self.finish()
        self.service.return_value.assign.assert_called_once_with("77", "9", "PN-1", "PRIMARY", "VARIANT", "variant", {})

    def test_assign_needs_a_product_and_the_primary_field_and_for_a_variant_the_column(self):
        design = mock.Mock()
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        cfg = self.config.config.workspaces[PORTFOLIO_KIND]
        for payload in ({"item": ""}, {"item": "9"}):   # no product; no Primary component field set
            self.assertFalse(self.reads.assign(dict(payload, token="t1"))["ok"])
        cfg.component_field = "PRIMARY"
        self.assertFalse(self.reads.assign({"token": "t1", "item": "9", "mode": "variant"})["pending"])   # no variants column
        self.assertFalse(self.reads.assign({"token": "t1", "item": "9", "mode": "other"})["pending"])
        self.assertEqual(self.queued, [])
        design.ref.assert_not_called()

    def test_usage_asks_for_the_number_of_the_open_design_and_gives_the_settings_fields(self):
        cfg = self.config.config.workspaces[PORTFOLIO_KIND]
        cfg.component_field, cfg.variants.link_column = "PRIMARY", "VARIANT"
        design = mock.Mock()
        design.number.return_value = "PN-1"
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        self.service.return_value.usage.return_value = {"primary": [], "variants": []}
        self.reads.usage({"token": "t1"})
        self.finish()
        self.service.return_value.usage.assert_called_once_with("77", "PN-1", "PRIMARY", "VARIANT")
        self.assertTrue(self.reads.status({"token": "t1"})["ok"])

    def test_usage_of_a_design_with_no_item_number_is_an_answer_and_not_an_error(self):
        self.config.config.workspaces[PORTFOLIO_KIND].component_field = "PRIMARY"
        design = mock.Mock()
        design.number.side_effect = NoItemNumber("No item number yet.")
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        self.reads.usage({"token": "t1"})
        self.finish()
        answer = self.reads.status({"token": "t1"})
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["result"], {"unpublished": True, "message": "No item number yet."})
        self.service.return_value.usage.assert_not_called()

    def test_design_gives_the_data_model_details_and_the_revision_and_state_of_its_item(self):
        design = mock.Mock()
        design.describe.return_value = {"number": "PN-1", "name": "Axle", "thumbnail_url": "https://x/t.png"}
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        with mock.patch.object(product_actions, "ComponentService") as components:
            components.return_value.revision_and_state.return_value = ("B", "Released")
            self.reads.design({"token": "t1"})
            self.finish()
        components.return_value.revision_and_state.assert_called_once_with("PN-1")
        self.assertEqual(self.reads.status({"token": "t1"})["result"], {"number": "PN-1", "name": "Axle", "thumbnail_url": "https://x/t.png",
                                                                       "revision": "B", "state": "Released"})

    def test_design_with_no_item_in_fusion_manage_still_gives_its_details(self):
        design = mock.Mock()
        design.describe.return_value = {"number": "PN-1", "name": "Axle", "thumbnail_url": ""}
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        with mock.patch.object(product_actions, "ComponentService") as components:
            components.return_value.revision_and_state.return_value = ("", "")
            self.reads.design({"token": "t1"})
            self.finish()
        result = self.reads.status({"token": "t1"})["result"]
        self.assertEqual((result["name"], result["revision"], result["state"]), ("Axle", "", ""))

    def test_design_that_is_not_saved_gives_blank_details_and_not_an_error(self):
        design = mock.Mock()
        design.describe.side_effect = NoItemNumber("Save the design first.")
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        self.reads.design({"token": "t1"})
        self.finish()
        answer = self.reads.status({"token": "t1"})
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["result"]["name"], "")

    def test_design_file_reads_the_lineage_of_the_component_item(self):
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, mock.Mock(), contexts=CONTEXTS)
        with mock.patch.object(product_actions, "ComponentService") as components:
            components.return_value.design_file.return_value = "urn:adsk.wipprod:dm.lineage:abc"
            self.reads.design_file({"token": "t1", "link": "/api/v3/workspaces/57/items/15677"})
            self.finish()
        components.return_value.design_file.assert_called_once_with("/api/v3/workspaces/57/items/15677")
        self.assertEqual(self.reads.status({"token": "t1"})["result"], {"file": "urn:adsk.wipprod:dm.lineage:abc"})

    def test_usage_needs_the_primary_field(self):
        design = mock.Mock()
        self.reads = ProductReads(self.config, lambda: object(), self.queued.append, design, contexts=CONTEXTS)
        self.assertFalse(self.reads.usage({"token": "t1"})["ok"])
        self.assertEqual(self.queued, [])

    def test_without_the_workspace_it_says_so(self):
        self.config.config.workspaces = {}
        for answer in (self.reads.views({"token": "t1"}), self.reads.rows({"token": "t3"}), self.reads.create({"token": "t2", "values": {"A": "x"}}),
                       self.reads.form({"token": "t4"})):
            self.assertEqual((answer["ok"], answer["pending"]), (False, False))
            self.assertIn("not set up", answer["message"])

    def test_the_page_listens_for_the_answer_of_every_action(self):
        """An action the page does not listen for answers into the void: its card or list waits for ever."""
        scripts = Path(product_actions.__file__).parents[1] / "web" / "products" / "js"
        page = "".join((scripts / name).read_text(encoding="utf-8") for name in ("products-page.js", "usage.js"))   # the scripts that listen (browse.js only asks)
        bridge = MessageBridge()
        with mock.patch.object(product_actions, "FmClient"):
            product_actions.register_product_actions(bridge, self.config, mock.Mock())
        for action in bridge._handlers:
            with self.subTest(action=action):
                self.assertIn("'%s'" % action, page)

    def test_a_product_is_read_for_browsing_with_the_fields_of_the_settings(self):
        self.config.config.workspaces[PORTFOLIO_KIND] = WorkspaceConfig(workspace_id="77", component_field="PRIMARY",
                                                                        variants=VariantsConfig(link_column="VARIANT"))
        self.service.return_value.contents.return_value = {"product": "24-1 - Gearbox"}
        self.reads.contents({"token": "t1", "item": "901"})
        self.finish()
        self.service.return_value.contents.assert_called_once_with("77", "901", "PRIMARY", "VARIANT")
        self.assertEqual(self.reads.status({"token": "t1"})["result"], {"product": "24-1 - Gearbox"})

    def test_a_product_is_not_read_for_browsing_without_one_chosen_or_the_primary_field(self):
        answer = self.reads.contents({"token": "t1", "item": ""})
        self.assertEqual(answer["ok"], False)
        answer = self.reads.contents({"token": "t2", "item": "901"})   # no Primary component field in the settings
        self.assertEqual(answer["ok"], False)

    def test_a_product_is_read_for_browsing_as_the_item_panel_reads_an_item(self):
        with mock.patch.object(product_actions, "ItemViewService") as service, mock.patch.object(product_actions, "granted", return_value={"view_items"}), \
                mock.patch.object(product_actions, "TabService") as tabs:
            service.return_value.read.return_value = {"title": "24-000002 - Universal Joint", "state": "Proposal", "tabs": {"item": {"label": "Product"}}}
            tabs.return_value.labels.return_value = {"PART_GRID": "Product Variants"}
            self.reads.view({"token": "t1", "item": "901"})
            self.finish()
        service.return_value.read.assert_called_once_with("77", "901", {"view_items"})
        result = self.reads.status({"token": "t1"})["result"]
        self.assertEqual((result["state"], result["stamp"], result["tabs"]["grid"]["label"]), ("Proposal", "stamp-1", "Product Variants"))

    def test_a_product_has_no_grid_tab_when_the_workspace_lists_none(self):
        with mock.patch.object(product_actions, "ItemViewService") as service, mock.patch.object(product_actions, "granted", return_value=set()),                 mock.patch.object(product_actions, "TabService") as tabs:
            service.return_value.read.return_value = {"title": "x", "state": "", "tabs": {"item": {"label": "Product"}}}
            tabs.return_value.labels.return_value = {"ITEM_DETAILS": "Product"}
            self.reads.view({"token": "t1", "item": "901"})
            self.finish()
        self.assertEqual(list(self.reads.status({"token": "t1"})["result"]["tabs"]), ["item"])

    def test_the_window_is_told_which_way_it_was_opened(self):
        bridge = MessageBridge()
        with mock.patch.object(product_actions, "FmClient"):
            product_actions.register_product_actions(bridge, self.config, mock.Mock())
        for mode in (BROWSE, USAGE):
            PRODUCT_MODE.mode = mode
            self.assertEqual(bridge.dispatch("products_mode", "{}")["result"], {"mode": mode})

    def test_the_actions_are_registered(self):
        bridge = MessageBridge()
        with mock.patch.object(product_actions, "FmClient"):
            product_actions.register_product_actions(bridge, self.config, mock.Mock())
        for action in ("products_views", "products_rows", "products_form", "products_options", "products_create", "products_item", "products_update", "products_picture", "products_usage", "products_design", "products_design_file", "products_status"):
            with self.subTest(action=action):
                self.assertTrue(bridge.dispatch(action, '{"token": "x"}')["ok"])


class SetupProblemTests(unittest.TestCase):
    def test_the_portfolio_workspace_needs_only_its_id(self):
        self.assertEqual(WorkspaceConfig(workspace_id="77").setup_problem("Portfolio Management", False), "")
        self.assertIn("not set", WorkspaceConfig().setup_problem("Portfolio Management", False))
        self.assertNotEqual(WorkspaceConfig(workspace_id="77").setup_problem("Items"), "")   # the Items workspace still needs its mapping


if __name__ == "__main__":
    unittest.main()

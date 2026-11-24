"""A new manufacturing item and a bought version of a made one: the rules of ``publish.bought_items`` (the actions that carry them are tested in ``test_products``)."""

import threading
import unittest
from unittest import mock

from src.config.workspace_models import FieldMapping, MakeBuyConfig, WorkspaceConfig
from src.fm.client import FmApiError, SendResult
from src.fm.refusal import FmRefused
from src.fm.v1_search import V1Row
from src.fm.workspace_form import parse_form
from src.publish import bought_items, products
from src.publish.bought_items import BoughtItems, form_value, plan_copy, specs_of, without

MAKE, BUY = "/api/v3/lookups/MAKEBUY/options/1", "/api/v3/lookups/MAKEBUY/options/2"
OPTIONS = {"MAKEBUY": [{"value": MAKE, "title": "Make"}, {"value": BUY, "title": "Buy"}]}
WS = "242"
PICTURE = "data:image/png;base64,AAAA"


def _field(field_id, type_title="Single Line Text", **more):
    return {"__self__": f"/api/v3/workspaces/{WS}/fields/{field_id}", "name": field_id.title(), "type": {"title": type_title}, **more}


def _linking(field_id):
    return _field(field_id, "Single Selection", picklist="/api/v3/lookups/ITEMS_ALL", picklistFieldDefinition="/api/v3/workspaces/242/views/1/fields/DESCRIPTOR")


ROWS = [
    _field("NUMBER", editability="NEVER", description="The item number will automatically be assigned", fieldLength=20),
    _field("TITLE", fieldValidators=[{"validatorName": "required", "variables": {}}]),
    _field("NOTES", "Paragraph"),
    _field("MAKE_BUY", "Single Selection", picklist="/api/v3/lookups/MAKEBUY"),
    _linking("SOURCE"), _linking("COMPONENT"), _linking("SUPPLIER"),
    _field("PICTURE", "Image"),
    _field("WEIGHT", "Float"), _field("DUE", "Date"), _field("ACTIVE", "Check Box"), _field("COUNT", "Integer"),
    _field("TOTAL", "Float", formulaField=True),
    _field("HIDDEN", visibility="NEVER"),
]
SECTIONS = [{"__self__": f"/api/v3/workspaces/{WS}/sections/1", "title": "Basic", "fields": [
    {"__self__": f"/api/v3/workspaces/{WS}/views/1/fields/{i}"} for i in
    ("NUMBER", "TITLE", "NOTES", "MAKE_BUY", "SOURCE", "COMPONENT", "SUPPLIER", "PICTURE", "WEIGHT", "DUE", "ACTIVE", "COUNT", "TOTAL", "HIDDEN")]}]
FORM = parse_form(ROWS, SECTIONS, OPTIONS)

SOURCE = {"NUMBER": "PN-1", "TITLE": "Axle", "NOTES": "Steel", "MAKE_BUY": {"link": MAKE, "title": "Make"}, "COMPONENT": {"link": "/c/1", "title": "PN-1 - Axle"},
          "SUPPLIER": {"link": "/api/v3/workspaces/9/items/4", "title": "ACME"}, "PICTURE": {"link": "/api/v3/workspaces/242/items/5/image"},
          "WEIGHT": 2.5, "DUE": "2026-12-01", "ACTIVE": True, "COUNT": 3, "TOTAL": 7, "SOURCE": None}
SECTION_LINKS = {i: f"/api/v3/workspaces/{WS}/sections/1" for i in
                 ("NUMBER", "TITLE", "NOTES", "MAKE_BUY", "SOURCE", "COMPONENT", "SUPPLIER", "PICTURE", "WEIGHT", "DUE", "ACTIVE", "COUNT")}


def config(**more):
    return WorkspaceConfig(**{"workspace_id": WS, "mappings": [FieldMapping("item_number", "NUMBER")], "component_field": "COMPONENT",
                              "make_buy": MakeBuyConfig("MAKE_BUY", MAKE, BUY, "SOURCE", "-B"), **more})


class Rig(unittest.TestCase):
    """A client that records what it is sent, and the readers of the workspace patched to the fixtures above."""

    def setUp(self):
        self.client = mock.Mock()
        self.client.send_json.return_value = SendResult(201, {"Location": f"/api/v3/workspaces/{WS}/items/901"}, None)
        self.source = dict(SOURCE)
        self.picture = mock.Mock(return_value=PICTURE)   # the source's picture as the data uri it is read as
        self.taken = mock.Mock(return_value=False)
        self.found = []   # rows of the v1 search for bought versions
        self.form = mock.Mock()
        self.form.return_value.form.side_effect = lambda ws: FORM
        self.items = mock.Mock()
        self.items.return_value.read_named.side_effect = lambda ws, item: ("PN-1 - Axle", self.source)
        self.mbom = mock.Mock()
        self.mbom.return_value.number_taken = lambda ws, number: self.taken(ws, number)
        self.v1 = mock.Mock()
        self.v1.return_value.rows.side_effect = lambda *args: self.found
        self.hits = [{"id": "17", "descriptor": "PN-1 - Axle"}]   # what the search by item number finds
        self.finder = mock.Mock()
        self.finder.return_value.search.side_effect = lambda ws, number: list(self.hits)
        self.sections = mock.Mock()
        self.sections.return_value.field_sections.return_value = SECTION_LINKS
        for module, name, fake in ((bought_items, "WorkspaceFormService", self.form), (bought_items, "ItemService", self.items),
                                   (bought_items, "MbomService", self.mbom), (bought_items, "load_image", self.picture), (bought_items, "ItemFinder", self.finder), (bought_items, "V1SearchService", self.v1),
                                   (products, "SectionService", self.sections)):
            patcher = mock.patch.object(module, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def maker(self, cfg=None):
        return BoughtItems(self.client, WS, cfg or config())

    def sent(self):
        """``{field id: value}`` of the one request sent."""
        (method, url, body), = [call[0] for call in self.client.send_json.call_args_list]
        self.assertEqual((method, url), ("POST", f"/api/v3/workspaces/{WS}/items"))
        return {f["__self__"].rsplit("/", 1)[1]: f["value"] for s in body["sections"] for f in s["fields"]}


class FormValueTests(unittest.TestCase):
    def spec(self, kind):
        return {"id": "F", "title": "Field", "kind": kind}

    def test_each_kind_takes_the_shape_the_form_sends(self):
        link = {"link": "/x/1", "title": "T"}
        cases = [("text", "a", "a"), ("textarea", "a", "a"), ("date", "2026-01-02", "2026-01-02"), ("integer", 3, "3"), ("number", 2.5, "2.5"),
                 ("number", "2.5", "2.5"), ("checkbox", True, True), ("select", link, "/x/1"), ("radio", link, "/x/1"), ("link", link, {"link": "/x/1"}),
                 ("links", [link, link], [{"link": "/x/1"}, {"link": "/x/1"}])]
        for kind, held, wanted in cases:
            self.assertEqual(form_value(self.spec(kind), held), wanted, kind)

    def test_a_checkbox_held_as_text_is_read_as_ticked_or_not(self):
        self.assertIs(form_value(self.spec("checkbox"), "true"), True)
        self.assertIs(form_value(self.spec("checkbox"), " True "), True)
        self.assertIsNone(form_value(self.spec("checkbox"), "false"))

    def test_a_blank_is_none(self):
        for kind in ("text", "link", "links", "checkbox", "number"):
            for blank in (None, "", "  ", []):
                self.assertIsNone(form_value(self.spec(kind), blank))
        self.assertIsNone(form_value(self.spec("checkbox"), False))

    def test_a_shape_that_is_not_understood_raises(self):
        for kind, held in (("text", {"link": "x"}), ("date", "01/02/2026"), ("number", True), ("checkbox", "yes"), ("checkbox", {"a": 1}), ("select", "x"), ("link", "x"),
                           ("links", {"link": "x"}), ("links", ["x"]), ("select", {"title": "no link"}), ("image", "x")):
            with self.assertRaises(FmApiError, msg=(kind, held)):
                form_value(self.spec(kind), held)


class PlanCopyTests(unittest.TestCase):
    def plan(self, **source):
        return plan_copy(FORM, {**SOURCE, **source}, config().make_buy, "NUMBER", "COMPONENT")

    def test_what_the_form_takes_is_copied_in_the_shape_the_form_sends(self):
        values, _ = self.plan()
        self.assertEqual(values, {"TITLE": "Axle", "NOTES": "Steel", "SUPPLIER": {"link": "/api/v3/workspaces/9/items/4"}, "WEIGHT": "2.5",
                                  "DUE": "2026-12-01", "ACTIVE": True, "COUNT": "3"})

    def test_the_skips_are_the_number_make_or_buy_the_source_link_the_component_link_and_pictures(self):
        _, skipped = self.plan()
        self.assertEqual({item["field"] for item in skipped}, {"NUMBER", "MAKE_BUY", "SOURCE", "COMPONENT", "PICTURE"})
        self.assertTrue(all(item["reason"] for item in skipped))

    def test_a_computed_hidden_or_unknown_field_is_never_copied_because_the_form_does_not_have_it(self):
        values, skipped = self.plan(TOTAL=9, HIDDEN="x", UNKNOWN="y")
        self.assertFalse({"TOTAL", "HIDDEN", "UNKNOWN"} & (set(values) | {item["field"] for item in skipped}))

    def test_a_field_that_settings_leaves_out_is_not_copied(self):
        cfg = config()
        cfg.make_buy.skip_fields = ["NOTES", "COUNT", "UNKNOWN"]
        values, _ = plan_copy(FORM, SOURCE, cfg.make_buy, "NUMBER", "COMPONENT")
        self.assertNotIn("NOTES", values)
        self.assertNotIn("COUNT", values)
        self.assertIn("TITLE", values)

    def test_leaving_out_every_field_copies_nothing(self):
        cfg = config()
        cfg.make_buy.skip_fields = list(specs_of(FORM))
        self.assertEqual(plan_copy(FORM, SOURCE, cfg.make_buy, "NUMBER", "COMPONENT")[0], {})

    def test_the_fields_left_out_survive_a_save_and_drop_blanks_and_repeats(self):
        cfg = config()
        cfg.make_buy.skip_fields = ["A", "B"]
        self.assertEqual(WorkspaceConfig.from_dict(cfg.to_dict()).make_buy.skip_fields, ["A", "B"])
        data = cfg.to_dict()
        data["make_buy"]["skip_fields"] = ["A", " ", "A", "B"]
        self.assertEqual(WorkspaceConfig.from_dict(data).make_buy.skip_fields, ["A", "B"])
        data["make_buy"]["skip_fields"] = "A"
        self.assertEqual(WorkspaceConfig.from_dict(data).make_buy.skip_fields, [])
        self.assertFalse(MakeBuyConfig(skip_fields=["A"]).is_touched())

    def test_a_blank_value_is_not_copied(self):
        self.assertNotIn("NOTES", self.plan(NOTES="")[0])

    def test_the_form_without_the_skipped_fields_holds_the_rest(self):
        _, skipped = self.plan()
        shown = set(specs_of(without(FORM, {item["field"] for item in skipped})))
        self.assertEqual(shown, {"TITLE", "NOTES", "SUPPLIER", "WEIGHT", "DUE", "ACTIVE", "COUNT"})


class AssemblyTests(Rig):
    def test_the_form_has_the_number_as_a_required_text_field_and_make_or_buy_locked_in_its_section(self):
        answer = self.maker().assembly_form()
        specs = specs_of(answer["form"])
        self.assertEqual(answer["number_field"], "NUMBER")
        self.assertEqual((specs["NUMBER"]["kind"], specs["NUMBER"]["required"]), ("text", True))
        self.assertIn("MAKE_BUY", specs)
        self.assertEqual(answer["locked"], {"MAKE_BUY": "Make"})

    def test_without_make_or_buy_set_up_nothing_is_locked_and_the_field_stays(self):
        answer = self.maker(config(make_buy=MakeBuyConfig())).assembly_form()
        self.assertEqual(answer["locked"], {})
        self.assertIn("MAKE_BUY", specs_of(answer["form"]))

    def test_a_make_value_that_is_not_an_option_of_the_field_is_said(self):
        cfg = config()
        cfg.make_buy.make_value = "/api/v3/lookups/MAKEBUY/options/9"
        with self.assertRaisesRegex(FmApiError, "no option"):
            self.maker(cfg).assembly_form()

    def test_a_create_sets_make_whatever_the_form_says_and_answers_the_number(self):
        answer = self.maker().create_assembly({"NUMBER": " A-1 ", "TITLE": "Frame", "MAKE_BUY": BUY})
        self.assertEqual(answer, {"id": "901", "link": f"/api/v3/workspaces/{WS}/items/901", "number": "A-1"})
        self.assertEqual(self.sent(), {"NUMBER": "A-1", "TITLE": "Frame", "MAKE_BUY": {"link": MAKE}})

    def test_a_number_is_required(self):
        with self.assertRaises(FmRefused) as raised:
            self.maker().create_assembly({"TITLE": "Frame"})
        self.assertEqual(set(raised.exception.fields), {"NUMBER"})
        self.client.send_json.assert_not_called()

    def test_a_taken_number_is_refused_beside_the_number_field_and_nothing_is_sent(self):
        self.taken.return_value = True
        with self.assertRaises(FmRefused) as raised:
            self.maker().create_assembly({"NUMBER": "A-1"})
        self.assertIn("A-1", raised.exception.fields["NUMBER"])
        self.client.send_json.assert_not_called()


class BoughtFormTests(Rig):
    def test_the_form_gives_the_new_number_the_copied_values_and_what_is_locked(self):
        answer = self.maker().open("17")
        self.assertEqual(answer["number"], "PN-1-B")
        self.assertEqual(answer["values"]["TITLE"], "Axle")
        self.assertEqual(set(answer), {"form", "number", "number_field", "values", "locked", "source_id"})
        self.assertEqual(answer["source_id"], "17")
        locked = {"NUMBER": "PN-1-B", "MAKE_BUY": "Buy", "SOURCE": "PN-1 - Axle"}
        self.assertEqual({field: text for field, text in answer["locked"].items() if field != "COMPONENT"}, locked)
        self.assertEqual(answer["number_field"], "NUMBER")
        self.assertEqual(set(specs_of(answer["form"])), {"TITLE", "NOTES", "SUPPLIER", "WEIGHT", "DUE", "ACTIVE", "COUNT"} | set(answer["locked"]))
        self.assertNotIn("PICTURE", specs_of(answer["form"]))
        self.assertEqual(self.items.return_value.read_named.call_args[0], (WS, "17"))

    def test_a_source_that_is_already_bought_is_refused(self):
        self.source["MAKE_BUY"] = {"link": BUY, "title": "Buy"}
        with self.assertRaisesRegex(FmApiError, "already a purchased item"):
            self.maker().open("17")

    def test_a_source_not_yet_classified_is_allowed(self):
        for held in (None, "", {"link": MAKE, "title": "Make"}):
            self.source["MAKE_BUY"] = held
            self.assertEqual(self.maker().open("17")["number"], "PN-1-B")

    def test_make_or_buy_not_set_up_is_said(self):
        with self.assertRaisesRegex(FmApiError, "not set up"):
            self.maker(config(make_buy=MakeBuyConfig())).open("17")

    def test_a_source_that_is_not_an_id_is_refused_before_anything_is_read(self):
        for source in ("", "17/../x", "abc"):
            with self.assertRaises(FmApiError):
                self.maker().open(source)
        self.items.return_value.read_named.assert_not_called()

    def test_a_source_given_by_neither_is_refused_before_anything_is_read(self):
        for source, number in (("", ""), ("", "  ")):
            with self.assertRaisesRegex(FmApiError, "Choose the item"):
                self.maker().open(source, number)
        self.finder.return_value.search.assert_not_called()
        self.items.return_value.read_named.assert_not_called()

    def test_an_id_with_the_number_the_page_expects_is_used_and_nothing_is_searched_by_number(self):
        answer = self.maker().open("17", "PN-1")
        self.assertEqual((answer["source_id"], answer["number"]), ("17", "PN-1-B"))
        self.finder.return_value.search.assert_not_called()
        self.assertEqual(self.items.return_value.read_named.call_args[0], (WS, "17"))

    def test_an_item_with_another_number_than_the_page_expects_is_shown_by_its_own_number_and_checked_by_it(self):
        self.source["NUMBER"] = "PN-2"
        self.taken.side_effect = lambda ws, number: number == "PN-2-B"
        with self.assertRaisesRegex(FmRefused, "PN-2-B"):   # the number the item has is checked, not the one the page expected
            self.maker().open("17", "PN-1")
        self.taken.side_effect = None
        self.assertEqual(self.maker().open("17", "PN-1")["number"], "PN-2-B")

    def test_the_item_the_form_and_the_three_searches_are_read_together(self):
        started = threading.Barrier(5, timeout=5)

        def meet(read):
            def go(*args):
                started.wait()   # the item, the form and the three searches are all under way before any answers
                return read(*args)
            return go
        self.items.return_value.read_named.side_effect = meet(lambda ws, item: ("PN-1 - Axle", self.source))
        self.form.return_value.form.side_effect = meet(lambda ws: FORM)
        self.taken.side_effect = meet(lambda ws, number: False)
        self.v1.return_value.rows.side_effect = meet(lambda *args: [])
        self.assertEqual(self.maker().open("17", "PN-1")["number"], "PN-1-B")   # a barrier that is not met in 5 seconds raises

    def test_a_search_or_a_read_that_fails_surfaces(self):
        for target in (self.items.return_value.read_named, self.form.return_value.form, self.v1.return_value.rows):
            saved = target.side_effect
            target.side_effect = FmApiError("down", 500)
            with self.assertRaisesRegex(FmApiError, "down"):
                self.maker().open("17", "PN-1")
            target.side_effect = saved
        self.mbom.return_value.number_taken = mock.Mock(side_effect=FmApiError("taken search down", 500))
        with self.assertRaisesRegex(FmApiError, "taken search down"):
            self.maker().open("17", "PN-1")

    def test_a_source_number_nothing_carries_is_refused_saying_to_publish_it_first(self):
        self.hits[:] = []
        with self.assertRaisesRegex(FmApiError, r"PN-1 is not in Fusion Manage yet. Publish it first"):
            self.maker().open(source_number="PN-1")
        self.items.return_value.read_named.assert_not_called()

    def test_a_source_number_several_items_share_is_refused(self):
        self.hits[:] = [{"id": "17", "descriptor": "PN-1 - Axle"}, {"id": "18", "descriptor": "PN-1 - Shaft"}]
        with self.assertRaisesRegex(FmApiError, r"Several Fusion Manage items carry item number PN-1"):
            self.maker().open(source_number=" PN-1 ")
        self.items.return_value.read_named.assert_not_called()

    def test_a_source_number_with_one_hit_goes_on_as_that_items_id(self):
        form = self.maker().open(source_number="PN-1")
        self.assertEqual(form["number"], "PN-1-B")
        self.assertEqual(self.items.return_value.read_named.call_args[0], (WS, "17"))
        self.finder.assert_called_once_with(self.client)
        self.finder.return_value.search.assert_called_once_with(WS, "PN-1")

    def test_a_source_with_no_number_is_refused(self):
        self.source["NUMBER"] = ""
        with self.assertRaisesRegex(FmApiError, "no item number"):
            self.maker().open("17")

    def test_a_number_longer_than_its_field_takes_is_refused(self):
        self.source["NUMBER"] = "N" * 19   # the form's number field holds 20; the suffix makes 21
        FORM_NUMBER = {**ROWS[0], "editability": "ALWAYS", "fieldLength": 20}
        rows = [FORM_NUMBER] + ROWS[1:]
        self.form.return_value.form.side_effect = lambda ws: parse_form(rows, SECTIONS, OPTIONS)
        with self.assertRaisesRegex(FmApiError, "20"):
            self.maker().open("17")

    def test_the_suffix_is_added_to_the_number_the_source_holds(self):
        cfg = config()
        cfg.make_buy.suffix = ".BUY"
        self.assertEqual(self.maker(cfg).open("17")["number"], "PN-1.BUY")

    def test_a_taken_number_is_refused_naming_it(self):
        self.taken.return_value = True
        with self.assertRaisesRegex(FmRefused, "PN-1-B"):
            self.maker().open("17")

    def test_a_source_that_has_a_bought_version_already_is_refused_naming_it(self):
        self.found = [V1Row("30", {"NUMBER": "PN-1-OLD"}, (("SOURCE", "PN-1 - Axle [REV:w]"), ("NUMBER", "PN-1-OLD")))]
        with self.assertRaisesRegex(FmRefused, "PN-1-OLD"):
            self.maker().open("17")

    def test_an_item_whose_source_is_another_number_is_not_a_bought_version(self):
        self.found = [V1Row("30", {"NUMBER": "PN-10-B"}, (("SOURCE", "PN-10 - Gear"), ("NUMBER", "PN-10-B")))]
        self.assertEqual(self.maker().open("17")["number"], "PN-1-B")

    def test_an_item_made_from_a_number_that_starts_with_the_source_number_is_not_a_bought_version(self):
        self.found = [V1Row("30", {"NUMBER": "PN-1-2-B"}, (("SOURCE", "PN-1-2 - Axle"), ("NUMBER", "PN-1-2-B")))]
        self.assertEqual(self.maker().open("17")["number"], "PN-1-B")

    def test_a_search_that_fails_is_not_taken_as_free(self):
        self.v1.return_value.rows.side_effect = FmApiError("down", 500)
        with self.assertRaises(FmApiError):
            self.maker().open("17")

    def test_a_source_link_field_that_does_not_link_to_an_item_is_said(self):
        cfg = config()
        cfg.make_buy.source_field = "NOTES"
        with self.assertRaisesRegex(FmApiError, "links to one item"):
            self.maker(cfg).open("17")


class OpenFoundTests(Rig):
    def row(self, number, link, make_buy="Buy", item_id="30"):
        return V1Row(item_id, {"NUMBER": number, "DESCRIPTOR": number + " - Axle"},
                     (("SOURCE", link), ("NUMBER", number), ("MAKE_BUY", make_buy), ("DESCRIPTOR", number + " - Axle")))

    def test_a_bought_item_whose_source_link_names_the_source_is_found(self):
        self.client.base_url, self.client.tenant = "https://acme.autodeskplm360.net", "acme"
        self.found = [self.row("PN-1-B", "PN-1 - Axle [REV:w]")]
        url = f"https://acme.autodeskplm360.net/plm/workspaces/{WS}/items/itemDetails?view=full&tab=details&mode=view&itemId=urn%60adsk%2Cplm%60tenant%2Cworkspace%2Citem%60acme%2C{WS}%2C30"
        self.assertEqual(self.maker().open(source_number="PN-1"), {"found": {"id": "30", "link": f"/api/v3/workspaces/{WS}/items/30", "number": "PN-1-B", "url": url, "name": "Axle"}})

    def test_the_search_is_of_working_versions_whose_source_link_contains_the_number(self):
        self.maker().open(source_number="PN-1")
        searches = [call[0] for call in self.v1.return_value.rows.call_args_list]
        self.assertEqual(len(searches), 2, "the other is the search for an item made from the source under another number")
        _, fields, _, filters = next(call for call in searches if len(call[3]) == 2)
        self.assertEqual([f.id for f in fields][:3], ["SOURCE", "NUMBER", "MAKE_BUY"])
        self.assertEqual([(f.field_id, f.filter_id, f.value) for f in filters][0], ("SOURCE", bought_items.CONTAINS, "PN-1"))

    def test_an_item_that_is_not_a_bought_one_or_names_another_source_is_not_taken(self):
        self.found = [self.row("PN-1-2-B", "PN-1-2 - Other"), self.row("PN-10-B", "PN-10 - Axle")]
        self.assertEqual(self.maker().open(source_number="PN-1")["number"], "PN-1-B", "the form is answered")
        self.found = [self.row("PN-1-X", "PN-1 - Axle", make_buy="Make")]   # not set to Buy: not offered, and refused as made from the source, as the form was
        with self.assertRaisesRegex(FmRefused, "PN-1-X"):
            self.maker().open(source_number="PN-1")

    def test_the_first_of_several_is_answered_and_none_found_gives_the_form(self):
        self.found = [self.row("PN-1-B", "PN-1", item_id="31"), self.row("PN-1-C", "PN-1", item_id="32")]
        self.assertEqual(self.maker().open(source_number="PN-1")["found"]["id"], "31")
        self.found = []
        self.assertNotIn("found", self.maker().open(source_number="PN-1"))

    def test_a_bought_version_is_found_before_a_taken_number_or_a_made_from_item_is_refused(self):
        self.taken.return_value = True   # the number is taken by that very item
        self.found = [self.row("PN-1-B", "PN-1 - Axle")]
        self.assertEqual(self.maker().open(source_number="PN-1")["found"]["id"], "30")
        self.taken.return_value = False
        self.found = [V1Row("30", {"NUMBER": "PN-1-OLD"}, (("SOURCE", "PN-1 - Axle"), ("NUMBER", "PN-1-OLD")))]   # made from it, not set to Buy: refused as before
        with self.assertRaisesRegex(FmRefused, "PN-1-OLD"):
            self.maker().open(source_number="PN-1")

    def test_a_source_that_is_not_in_fusion_manage_or_a_failed_search_raises(self):
        self.hits = []
        with self.assertRaisesRegex(FmApiError, "not in Fusion Manage"):
            self.maker().open(source_number="PN-1")
        self.hits = [{"id": "17", "descriptor": "PN-1 - Axle"}]
        self.v1.return_value.rows.side_effect = FmApiError("down", 500)
        with self.assertRaises(FmApiError):
            self.maker().open(source_number="PN-1")

    def test_not_set_up_is_refused_without_a_search(self):
        with self.assertRaisesRegex(FmApiError, "Make or buy"):
            self.maker(config(make_buy=MakeBuyConfig())).open(source_number="PN-1")
        self.v1.return_value.rows.assert_not_called()


class BoughtCreateTests(Rig):
    def test_a_source_number_is_found_again_by_the_create_and_a_repeat_is_refused(self):
        self.maker().open(source_number="PN-1")
        answer = self.maker().create_bought("", {"TITLE": "x"}, "PN-1")
        self.assertEqual(answer["number"], "PN-1-B")
        self.assertEqual(self.sent()["SOURCE"], {"link": f"/api/v3/workspaces/{WS}/items/17"})
        self.assertEqual(self.finder.return_value.search.call_count, 2)   # the form's answer is not trusted
        self.hits[:] = []   # the item is gone: the create says so and sends nothing more
        self.client.send_json.reset_mock()
        with self.assertRaisesRegex(FmApiError, "not in Fusion Manage yet"):
            self.maker().create_bought("", {"TITLE": "x"}, "PN-1")
        self.client.send_json.assert_not_called()
        self.hits[:] = [{"id": "17", "descriptor": "PN-1 - Axle"}]
        self.taken.return_value = True   # a repeat: the bought version exists now
        with self.assertRaisesRegex(FmRefused, "exists already"):
            self.maker().create_bought("", {"TITLE": "x"}, "PN-1")
        self.client.send_json.assert_not_called()

    def test_the_values_of_the_form_are_sent_with_the_number_make_or_buy_and_the_source_set_here(self):
        form = self.maker().open("17")
        posted = {**form["values"], "TITLE": "Axle, bought", "NUMBER": "HACKED", "MAKE_BUY": MAKE, "SOURCE": {"link": "/other"}, "COMPONENT": {"link": "/c/9"}}
        answer = self.maker().create_bought("17", posted)
        self.assertEqual(answer, {"id": "901", "link": f"/api/v3/workspaces/{WS}/items/901", "number": "PN-1-B"})
        sent = self.sent()
        self.assertEqual((sent["NUMBER"], sent["TITLE"]), ("PN-1-B", "Axle, bought"))
        self.assertEqual(sent["MAKE_BUY"], {"link": BUY})
        self.assertEqual(sent["SOURCE"], {"link": f"/api/v3/workspaces/{WS}/items/17"})
        self.assertNotIn("COMPONENT", sent)

    def test_values_of_fields_the_form_does_not_hold_are_not_sent(self):
        form = self.maker().open("17")
        self.maker().create_bought("17", {**form["values"], "NOT_ON_THE_FORM": "x"})
        self.assertNotIn("NOT_ON_THE_FORM", self.sent())

    def test_what_the_form_gave_round_trips_to_the_values_of_the_item(self):
        self.client.send_json.reset_mock()
        self.maker().create_bought("17", self.maker().open("17")["values"])
        sent = self.sent()
        for field in ("TITLE", "NOTES", "WEIGHT", "DUE", "ACTIVE", "COUNT"):
            self.assertEqual(sent[field], form_value(specs_of(FORM)[field], SOURCE[field]), field)
        self.assertEqual(sent["SUPPLIER"], {"link": "/api/v3/workspaces/9/items/4"})

    def test_no_request_but_the_create_of_the_item_is_sent_and_none_touches_a_bom(self):
        self.maker().create_bought("17", {"TITLE": "x"})
        urls = [call[0][1] for call in self.client.send_json.call_args_list]
        self.assertEqual(urls, [f"/api/v3/workspaces/{WS}/items"])
        self.assertFalse([call for call in self.client.get_json.call_args_list if "bom" in str(call)])

    def test_a_source_that_is_already_bought_sends_nothing(self):
        self.source["MAKE_BUY"] = {"link": BUY}
        with self.assertRaises(FmApiError):
            self.maker().create_bought("17", {"TITLE": "x"})
        self.client.send_json.assert_not_called()

    def test_a_refusal_of_fusion_manage_is_passed_on_with_its_fields(self):
        body = '{"message": "Validation failed", "errors": [{"field": "TITLE", "message": "Too long"}]}'
        self.client.send_json.side_effect = FmApiError("HTTP 400", 400, body)
        with self.assertRaises(FmRefused) as raised:
            self.maker().create_bought("17", {"TITLE": "x"})
        self.assertEqual((str(raised.exception), raised.exception.fields), ("Validation failed", {"TITLE": "Too long"}))

    def test_a_plain_400_is_not_reported_as_a_bad_search(self):
        self.client.send_json.side_effect = FmApiError("HTTP 400", 400, "")
        with self.assertRaises(FmApiError) as raised:
            self.maker().create_bought("17", {"TITLE": "x"})
        self.assertNotEqual(raised.exception.status, 400)

    def test_two_creations_of_one_number_at_once_make_one_item(self):
        made = threading.Event()
        meeting = threading.Barrier(2)

        def taken(workspace, number):
            seen = made.is_set()   # what the check sees, before the other thread can change it
            try:
                meeting.wait(timeout=0.3)   # both threads get here before either goes on, unless the lock keeps one out
            except threading.BrokenBarrierError:
                pass
            return seen

        def send(method, url, body):
            made.set()
            return SendResult(201, {"Location": f"/api/v3/workspaces/{WS}/items/901"}, None)

        self.taken.side_effect = taken
        self.client.send_json.side_effect = send
        outcomes = []

        def run():
            try:
                outcomes.append(self.maker().create_bought("17", {"TITLE": "x"})["id"])
            except FmRefused as exc:
                outcomes.append(str(exc))

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.client.send_json.call_count, 1)
        self.assertEqual(sorted(outcomes, key=str.isdigit)[0].count("exists already"), 1)


if __name__ == "__main__":
    unittest.main()


class PictureTests(Rig):
    def test_the_picture_of_the_source_is_read_and_sent_with_the_create(self):
        self.maker().create_bought("17", {"TITLE": "x"})
        self.picture.assert_called_once_with(self.client, "/api/v3/workspaces/242/items/5/image")
        self.assertEqual(self.sent()["PICTURE"], PICTURE)

    def test_a_picture_in_the_values_of_a_page_is_never_taken_over_the_sources(self):
        self.maker().create_bought("17", {"TITLE": "x", "PICTURE": "data:image/png;base64,ZZZZ"})
        self.assertEqual(self.sent()["PICTURE"], PICTURE)

    def test_a_source_with_no_picture_sends_none(self):
        self.source["PICTURE"] = None
        self.maker().create_bought("17", {"TITLE": "x"})
        self.picture.assert_not_called()
        self.assertNotIn("PICTURE", self.sent())

    def test_a_field_settings_say_is_not_copied_has_its_picture_left_out(self):
        self.maker(config(make_buy=MakeBuyConfig("MAKE_BUY", MAKE, BUY, "SOURCE", "-B", skip_fields=("PICTURE",)))).create_bought("17", {"TITLE": "x"})
        self.picture.assert_not_called()
        self.assertNotIn("PICTURE", self.sent())

    def test_a_picture_that_cannot_be_read_refuses_the_create_and_sends_nothing(self):
        self.picture.return_value = ""
        with self.assertRaisesRegex(FmApiError, "picture of PN-1 could not be read"):
            self.maker().create_bought("17", {"TITLE": "x"})
        self.client.send_json.assert_not_called()

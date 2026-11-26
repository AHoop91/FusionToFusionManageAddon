"""Behaviours that were learnt the hard way, each named by what went wrong, so a change cannot quietly bring it back.

The incidents are those the code records in its comments (the 500 for a line body of the changed field alone, Fusion Manage's refusal of a
workspace link for an item that exists, a blank value clearing what the item held, a request resent after a lost answer). Where a test is also
covered from another side (``test_publish_failures``) this one holds the request itself.
"""

import shutil
import tempfile
import unittest

from src.fm.client import WORKSPACES
from src.publish.bom_requests import bom_requests
from src.publish.item_requests import item_request
from src.publish.placeholders import Unresolved, marker, resolve
from src.publish.states import DONE
from src.sync.property_compare import FOUND, MISMATCH, NEW
from tests.fake_manage import FakeManage, refusal
from tests.publish_helpers import add, create, remove, renumber, requantify, send, write_folder

WS = "57"
SECTIONS = {"TITLE": f"{WORKSPACES}/{WS}/sections/1", "MASS": f"{WORKSPACES}/{WS}/sections/2"}


def row(field, value, status=NEW):
    return {"name": field, "fm_field": field, "value": value, "status": status}


class ALineChangeNamesTheLineAndItsItemTests(unittest.TestCase):
    """A body that held only the changed field was answered with a 500: Fusion Manage wants the line as its own BOM tab sends it."""

    def test_a_quantity_change_sends_the_whole_line(self):
        request = bom_requests(WS, [requantify("A", "B", 1, "7", "55")])["A"][0]
        self.assertEqual(request["method"], "PATCH")
        body = request["body"]
        self.assertEqual(body["__self__"], request["url"])
        self.assertEqual(body["quantity"], "7")
        self.assertEqual((body["children"], body["fields"]), ([], []))
        self.assertEqual(set(body["item"]), {"link", "urn", "title", "deleted", "version"})
        self.assertEqual(body["item"]["version"], marker("version", "B"))

    def test_a_renumber_sends_the_whole_line_and_finds_it_by_the_number_it_has_now(self):
        request = bom_requests(WS, [renumber("A", "B", 1, 4)])["A"][0]
        self.assertIn(marker("edge", "A>B@1"), request["url"])   # by the number it has, not the one it is given
        self.assertEqual(request["body"]["itemNumber"], 4)
        self.assertEqual(request["body"]["__self__"], request["url"])

    def test_a_line_number_is_a_number_to_fusion_manage_and_text_when_it_is_not_one(self):
        numbers = {"3": 3, " 3 ": 3, "03": 3, "3a": "3a", "": "", "-1": "-1", "1.5": "1.5", "٣": "٣"}   # the last is an Arabic-Indic digit
        for given, sent in numbers.items():
            with self.subTest(given=given):
                body = bom_requests(WS, [add("A", "B", given)])["A"][0]["body"]
                self.assertEqual(body["itemNumber"], sent)
                self.assertEqual(type(body["itemNumber"]), type(sent))


class ABlankQuantityNeverClearsTheLineTests(unittest.TestCase):
    def test_an_update_with_no_quantity_makes_no_request(self):
        for quantity in ("", "  ", None):
            with self.subTest(quantity=quantity):
                self.assertEqual(bom_requests(WS, [requantify("A", "B", 1, quantity, "5")]), {})

    def test_an_add_or_renumber_with_no_quantity_leaves_the_key_out(self):
        for op in (add("A", "B", 1, ""), renumber("A", "B", 1, 2, "5")):
            with self.subTest(op=op["op"]):
                op = dict(op, quantity="")
                self.assertNotIn("quantity", bom_requests(WS, [op])["A"][0]["body"])

    def test_a_quantity_of_zero_is_a_quantity(self):
        self.assertEqual(bom_requests(WS, [requantify("A", "B", 1, "0", "5")])["A"][0]["body"]["quantity"], "0")


class TheOrderOfALinesRequestsTests(unittest.TestCase):
    def test_removals_come_before_renumbers_before_updates_before_additions(self):
        operations = [add("A", "N", 9), requantify("A", "Q", 2, "3", "7"), renumber("A", "R", 3, 4, "8"), remove("A", "D", 1, "9"), {"op": "teleport", "parent": "A", "number": "X"}]
        methods = [(r["method"]) for r in bom_requests(WS, operations)["A"]]
        self.assertEqual(methods, ["DELETE", "PATCH", "PATCH", "POST"])   # and the kind nobody knows makes no request at all

    def test_parents_are_kept_apart(self):
        by_parent = bom_requests(WS, [add("A", "N", 1), add("B", "N", 1), remove("A", "D", 2, "9")])
        self.assertEqual({parent: len(requests) for parent, requests in by_parent.items()}, {"A": 2, "B": 1})


class ABlankOrZeroValueOfAnItemTests(unittest.TestCase):
    """A blank value never overwrites what Fusion Manage holds; zero is a value."""

    def request(self, rows, state=NEW, item_id=""):
        fm = {"state": state, "item_id": item_id}
        return item_request(WS, fm, rows, [], SECTIONS)

    def values(self, request):
        return {f["__self__"].rsplit("/", 1)[-1]: f["value"] for s in request["body"]["sections"] for f in s["fields"]}

    def test_a_blank_value_is_not_sent(self):
        request, _ = self.request([row("TITLE", ""), row("MASS", "1")])
        self.assertEqual(self.values(request), {"MASS": "1"})

    def test_a_value_of_zero_is_sent(self):
        for zero in (0, 0.0, "0"):
            with self.subTest(zero=zero):
                request, _ = self.request([row("MASS", zero)])
                self.assertEqual(self.values(request), {"MASS": zero})

    @unittest.expectedFailure
    def test_only_blank_values_make_no_request_for_a_new_item_either(self):
        """LATENT: a new item with nothing to send gets a POST with an empty ``sections`` list, where an existing one gets no request. It
        cannot happen in a run today (the item number is mapped and an item without one is not published), so nothing is created empty."""
        request, reason = self.request([row("TITLE", ""), row("MASS", None)])
        self.assertIsNone(request)

    def test_only_blank_values_make_no_request_for_an_item_that_exists(self):
        request, reason = self.request([row("TITLE", "", MISMATCH)], FOUND, "9")
        self.assertIsNone(request)
        self.assertTrue(reason)

    def test_a_value_that_matches_is_not_sent_again(self):
        request, reason = self.request([row("TITLE", "Axle", "match")], FOUND, "9")
        self.assertIsNone(request)


class AnExistingItemIsWrittenThroughItsOwnSectionsTests(unittest.TestCase):
    """Fusion Manage refuses the workspace's section link for an item that exists ("Could not find section")."""

    def test_a_new_item_uses_the_workspaces_sections_and_an_existing_one_its_own(self):
        created, _ = item_request(WS, {"state": NEW}, [row("TITLE", "Axle")], [], SECTIONS)
        updated, _ = item_request(WS, {"state": FOUND, "item_id": "9"}, [row("TITLE", "Axle", MISMATCH)], [], SECTIONS)
        self.assertEqual(created["body"]["sections"][0]["link"], f"{WORKSPACES}/{WS}/sections/1")
        self.assertEqual(updated["body"]["sections"][0]["link"], f"{WORKSPACES}/{WS}/items/9/views/1/sections/1")
        self.assertEqual((created["method"], updated["method"]), ("POST", "PATCH"))
        self.assertTrue(updated["url"].endswith("/items/9"))

    def test_a_field_no_section_holds_stops_the_whole_item(self):
        request, reason = item_request(WS, {"state": NEW}, [row("TITLE", "Axle"), row("GHOST", "x")], [], SECTIONS)
        self.assertIsNone(request)
        self.assertIn("GHOST", reason)

    def test_an_update_with_no_id_is_refused(self):
        request, _ = item_request(WS, {"state": FOUND, "item_id": ""}, [row("TITLE", "Axle", MISMATCH)], [], SECTIONS)
        self.assertIsNone(request)


class AMarkerIsNeverReadTwiceTests(unittest.TestCase):
    def test_a_value_with_braces_in_it_is_put_in_as_it_is_and_not_read_for_markers(self):
        self.assertEqual(resolve({"t": "{{item:A}}"}, {("item", "a"): "{{item:B}}"}), {"t": "{{item:B}}"})

    def test_an_item_number_with_braces_cannot_be_made_a_marker(self):
        with self.assertRaises(ValueError):
            marker("item", "A{1}")
        with self.assertRaises(ValueError):
            bom_requests(WS, [add("P{", "N", 1)])   # refused at planning, before anything is sent

    def test_a_marker_with_no_value_names_what_is_missing_and_sends_nothing(self):
        with self.assertRaises(Unresolved) as raised:
            resolve({"url": "/items/{{item:Zed}}/bom-items", "body": {"v": "{{version:Zed}}"}}, {})
        self.assertEqual(raised.exception.keys, [("item", "zed"), ("version", "zed")])


class ItemNumbersAreTheSameInAnyCaseTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_the_id_of_an_item_just_made_is_found_without_a_search_whatever_the_case(self):
        tenant = FakeManage()
        tenant.fail("GET /api/v3/search-results", refusal(500, "no search"), times=10 ** 6)   # a line that cannot find its item by id has no way to find it
        write_folder(self.root, {"Pn-1": create("Pn-1"), "Ch-2": create("Ch-2")}, [add("PN-1", "ch-2", 1)])
        run = send(self.root, tenant)
        self.assertEqual(run.phase, DONE)
        self.assertEqual(tenant.lines_of("Pn-1"), [("Ch-2", 1, "1")])

    def test_a_parent_whose_create_was_refused_never_gets_lines_hung_on_another_item_with_its_number(self):
        tenant = FakeManage()
        other = tenant.add_item("F")   # an item that is not the one this send was to make
        tenant.add_item("B")
        write_folder(self.root, {"F": create("F")}, [add("F", "B", 1)])
        tenant.fail("POST /api/v3/workspaces/57/items", refusal(400, "error.item.invalid"), writes_only=True)
        run = send(self.root, tenant)
        self.assertEqual(tenant.bom[other], [])
        self.assertEqual(run.rows[-1]["status"], "error")

    def test_a_create_that_died_with_the_process_is_found_not_made_again(self):
        tenant = FakeManage()
        write_folder(self.root, {"E": create("E")}, [])

        def die(method, path, body):
            if method == "POST":
                raise RuntimeError("the process died after Fusion Manage made the item")

        tenant.on_done = die
        send(self.root, tenant)
        self.assertEqual(tenant.count_of("E"), 1)
        tenant.on_done = None
        run = send(self.root, tenant)
        self.assertEqual((run.phase, tenant.count_of("E")), (DONE, 1))

    """``PN-1`` and ``pn-1`` are one item: a line that names it in another case still finds it."""

    def test_a_line_naming_its_parent_and_child_in_another_case_lands_on_the_right_items(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        tenant = FakeManage()
        write_folder(root, {"Pn-1": create("Pn-1"), "Ch-2": create("Ch-2")}, [add("PN-1", "ch-2", 1)])
        run = send(root, tenant)
        self.assertEqual(run.phase, DONE, [r["detail"] for r in run.rows])
        self.assertEqual(tenant.lines_of("Pn-1"), [("Ch-2", 1, "1")])


if __name__ == "__main__":
    unittest.main()

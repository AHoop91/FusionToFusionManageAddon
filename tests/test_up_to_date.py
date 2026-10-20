import unittest
from types import SimpleNamespace
from unittest import mock

from src.sync import bom_compare, up_to_date
from src.sync.up_to_date import ShownItem, check_bom, check_properties


def row(number, level=0, quantity="1"):
    return {"level": level, "item_number": number, "part_number": number, "quantity": quantity}


def line(number, quantity="1"):
    return {"number": number, "quantity": quantity, "name": "", "sequence": ""}


def shown(summary, **reads):
    """A ShownItem whose design reads give ``summary`` and what ``reads`` says (``structure`` rows, ``properties``)."""
    design = mock.Mock()
    design.summary.return_value = summary
    design.structure.return_value = reads.get("structure", [])
    design.properties.return_value = reads.get("properties", [])
    cfg = SimpleNamespace(workspace_id="242", mappings=[], maps_physical=lambda: False)
    return ShownItem(design, "mfg", "fm", cfg, "model", "time", "TOP", "9")


class BomCheckTests(unittest.TestCase):
    def check(self, rows, fm_bom):
        with mock.patch.object(bom_compare, "BomService") as service:
            service.return_value.read.return_value = fm_bom
            return check_bom(shown({"item_number": "TOP"}, structure=rows))

    def test_components_where_the_item_has_them_are_ok(self):
        found = self.check([row("A"), row("B", quantity="2")], {"TOP": [line("A"), line("B", "2")]})
        self.assertEqual((found["state"], found["names"]), ("ok", []))

    def test_a_component_under_another_parent_is_out_of_date(self):
        found = self.check([row("A"), row("B", 1)], {"TOP": [line("A"), line("B")]})
        self.assertEqual((found["state"], found["names"], found["differences"]), ("changes", ["B"], 1))

    def test_a_component_not_under_the_parent_has_no_quantity_in_the_item(self):
        found = self.check([row("B", 1)], {"TOP": []})
        self.assertEqual(found["details"], [{"name": "B", "design": "1", "item": ""}])

    def test_a_line_only_fusion_manage_has_is_ok(self):
        self.assertEqual(self.check([row("A")], {"TOP": [line("A"), line("OIL")]})["state"], "ok")

    def test_an_item_that_is_not_the_top_of_the_design_is_not_compared(self):
        with mock.patch.object(bom_compare, "BomService") as service:
            found = check_bom(shown({"item_number": "OTHER"}))
        self.assertEqual(found, {"state": "unavailable"})
        service.assert_not_called()


class PropertiesCheckTests(unittest.TestCase):
    def check(self, rows, fm_state="found", summary=None):
        compared = {"fm": {"state": fm_state, "message": "no way"}, "rows": rows}
        with mock.patch.object(up_to_date, "read_and_compare", return_value=([], compared)) as compare:
            found = check_properties(shown(summary or {"item_number": "TOP"}))
        return found, compare

    def test_mapped_fields_that_differ_are_listed(self):
        found, _ = self.check([{"name": "Mass", "status": "mismatch"}, {"name": "Colour", "status": "new"},
                               {"name": "Part Number", "status": "match"}, {"name": "Notes", "status": "unmapped"}])
        self.assertEqual((found["state"], found["names"]), ("changes", ["Mass", "Colour"]))

    def test_each_difference_says_what_the_design_and_the_item_hold(self):
        found, _ = self.check([{"name": "Mass", "status": "mismatch", "value": "1.234567", "shown": "1.23", "fm_value": "2"}])
        self.assertEqual(found["details"], [{"name": "Mass", "design": "1.23", "item": "2"}])

    def test_fields_that_match_are_ok(self):
        self.assertEqual(self.check([{"name": "Mass", "status": "match"}])[0]["state"], "ok")

    def test_an_item_that_could_not_be_read_is_an_error_with_the_reason(self):
        self.assertEqual(self.check([], fm_state="unknown")[0], {"state": "error", "message": "no way"})

    def test_the_item_is_read_by_its_id_not_searched_for(self):
        _, compare = self.check([])
        self.assertEqual(compare.call_args.kwargs["known_id"], "9")

    def test_an_item_that_is_not_the_top_of_the_design_is_not_compared(self):
        found, compare = self.check([], summary={"item_number": "OTHER"})
        self.assertEqual(found, {"state": "unavailable"})
        compare.assert_not_called()


if __name__ == "__main__":
    unittest.main()

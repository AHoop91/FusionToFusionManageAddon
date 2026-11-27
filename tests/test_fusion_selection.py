"""What is selected or open in Fusion, and the Data Model reference of it (``fusion_selection``), read through fake Fusion objects."""

import types
import unittest
from unittest import mock

from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui import fusion_selection as sel


def part(number="PN-1", name="Part"):
    return types.SimpleNamespace(partNumber=number, name=name, entityToken="tok-" + str(number))


class ComponentOfTests(unittest.TestCase):
    def setUp(self):
        for name in ("Occurrence", "Component"):
            patcher = mock.patch.object(sel.adsk.fusion, name)
            setattr(self, name.lower(), patcher.start())
            self.addCleanup(patcher.stop)
        self.occurrence.cast.return_value = None
        self.component.cast.return_value = None

    def test_an_occurrence_gives_its_component(self):
        inner = part()
        self.occurrence.cast.return_value = types.SimpleNamespace(component=inner)
        self.assertIs(sel.component_of("e"), inner)

    def test_a_component_is_itself(self):
        inner = part()
        self.component.cast.return_value = inner
        self.assertIs(sel.component_of("e"), inner)

    def test_a_body_seen_through_an_occurrence_gives_the_component_of_that_occurrence(self):
        inner = part()
        entity = types.SimpleNamespace(assemblyContext=types.SimpleNamespace(component=inner))
        self.assertIs(sel.component_of(entity), inner)

    def test_a_body_with_no_occurrence_gives_its_parent_component(self):
        inner = part()
        entity = types.SimpleNamespace(assemblyContext=None, parentComponent=inner)
        self.assertIs(sel.component_of(entity), inner)

    def test_a_face_gives_the_parent_component_of_its_body(self):
        inner = part()
        entity = types.SimpleNamespace(body=types.SimpleNamespace(parentComponent=inner))   # no assemblyContext: an AttributeError
        self.assertIs(sel.component_of(entity), inner)

    def test_a_hop_that_fails_with_a_runtime_error_is_skipped(self):
        inner = part()

        class Entity:
            @property
            def assemblyContext(self):
                raise RuntimeError("gone")
            parentComponent = inner
        self.assertIs(sel.component_of(Entity()), inner)

    def test_an_entity_with_no_component_gives_none(self):
        self.assertIsNone(sel.component_of(object()))

    def test_an_object_with_no_type_gives_none(self):
        self.occurrence.cast.side_effect = TypeError("no type")
        self.assertIsNone(sel.component_of("tree top"))


class SelectedNumberTests(unittest.TestCase):
    def test_the_number_is_that_of_the_first_entity_that_has_a_component(self):
        components = {"a": None, "b": part(" PN-2 "), "c": part("PN-3")}
        with mock.patch.object(sel, "component_of", side_effect=components.get):
            self.assertEqual(sel.selected_component_number(["a", "b", "c"]), "PN-2")

    def test_no_component_gives_an_empty_number(self):
        with mock.patch.object(sel, "component_of", return_value=None):
            self.assertEqual(sel.selected_component_number(["a"]), "")
            self.assertEqual(sel.selected_component_number([]), "")

    def test_a_component_with_no_number_gives_an_empty_number(self):
        with mock.patch.object(sel, "component_of", return_value=part(None)):
            self.assertEqual(sel.selected_component_number(["a"]), "")


class SelectedPartNumberTests(unittest.TestCase):
    def number(self, selected="", drawing=False, design=None, from_menu=False, menu=()):
        sel.menu_selection[:] = list(menu)
        self.addCleanup(sel.menu_selection.clear)
        with mock.patch.object(sel, "active_selection", return_value=["active"]), \
                mock.patch.object(sel, "selected_component_number", return_value=selected) as read, \
                mock.patch.object(sel.drawing_source, "active_drawing", return_value=object() if drawing else None), \
                mock.patch.object(sel.drawing_source, "top_level_number", return_value=("DRW-1", "")), \
                mock.patch.object(sel, "open_design", return_value=design):
            return sel.selected_part_number(from_menu), read

    def test_the_selected_component_gives_its_number(self):
        self.assertEqual(self.number(selected="PN-2")[0], "PN-2")

    def test_nothing_selected_gives_the_number_of_the_top_of_the_open_design(self):
        design = types.SimpleNamespace(rootComponent=part(" ROOT "))
        self.assertEqual(self.number(design=design)[0], "ROOT")

    def test_no_design_gives_nothing(self):
        self.assertEqual(self.number()[0], "")

    def test_a_drawing_gives_the_number_of_the_design_it_shows(self):
        self.assertEqual(self.number(drawing=True)[0], "DRW-1")

    def test_the_active_selection_is_read_by_default(self):
        _number, read = self.number(selected="PN-2", menu=["menu"])
        self.assertEqual(read.call_args.args[0], ["active"])

    def test_the_menu_reads_what_was_selected_when_it_opened(self):
        _number, read = self.number(selected="PN-2", from_menu=True, menu=["menu"])
        self.assertEqual(read.call_args.args[0], ["menu"])


class RefTests(unittest.TestCase):
    def setUp(self):
        self.design = object()
        for name, value in (("open_design", self.design), ("active_selection", ["e"])):
            patcher = mock.patch.object(sel, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def in_document(self, drawing=False):
        return mock.patch.object(sel.drawing_source, "active_drawing", return_value=object() if drawing else None)

    def test_a_drawing_has_no_model_of_its_own(self):
        with self.in_document(drawing=True):
            self.assertIsNone(sel._own_ref("PN-1"))

    def test_the_selected_component_with_the_number_gives_its_own_ref(self):
        with self.in_document(), mock.patch.object(sel, "component_of", return_value=part("PN-1")), \
                mock.patch.object(sel, "component_ref", return_value="own") as make:
            self.assertEqual(sel._own_ref("PN-1"), "own")
        self.assertEqual(make.call_args.args[1], self.design)

    def test_no_selected_component_with_the_number_gives_none(self):
        with self.in_document(), mock.patch.object(sel, "component_of", return_value=part("PN-9")):
            self.assertIsNone(sel._own_ref("PN-1"))

    def test_a_drawing_gives_the_ref_of_the_design_it_shows(self):
        with self.in_document(drawing=True), mock.patch.object(sel.drawing_source, "referenced_design", return_value="shown"), \
                mock.patch.object(sel, "design_ref", return_value="drawn") as make:
            self.assertEqual(sel.active_ref(), "drawn")
        make.assert_called_once_with("shown")

    def test_a_design_gives_the_ref_of_the_open_design(self):
        with self.in_document(), mock.patch.object(sel, "active_design_ref", return_value="open"):
            self.assertEqual(sel.active_ref(), "open")

    def test_the_own_ref_wins_over_the_active_one(self):
        with mock.patch.object(sel, "_own_ref", return_value="own"), mock.patch.object(sel, "active_ref", return_value="active"):
            self.assertEqual(sel.part_ref("PN-1"), "own")

    def test_the_active_ref_is_used_when_there_is_no_own_one(self):
        with mock.patch.object(sel, "_own_ref", return_value=None), mock.patch.object(sel, "active_ref", return_value="active"):
            self.assertEqual(sel.part_ref("PN-1"), "active")


class SelectsRootTests(unittest.TestCase):
    def selects(self, design, cast):
        with mock.patch.object(sel, "open_design", return_value=design), mock.patch.object(sel.adsk.fusion, "Component") as component:
            component.cast.side_effect = cast
            return sel.selects_root(["a", "b"])

    def test_no_design_selects_no_root(self):
        self.assertFalse(self.selects(None, lambda e: None))

    def test_the_root_component_is_found_among_the_entities(self):
        design = types.SimpleNamespace(rootComponent=part("ROOT"))
        self.assertTrue(self.selects(design, {"a": None, "b": part("ROOT")}.get))

    def test_a_body_inside_the_root_is_not_the_root(self):
        design = types.SimpleNamespace(rootComponent=part("ROOT"))
        self.assertFalse(self.selects(design, lambda e: None))
        self.assertFalse(self.selects(design, lambda e: part("OTHER")))


class RestoreMenuSelectionTests(unittest.TestCase):
    def test_what_was_selected_when_the_menu_opened_is_selected_again(self):
        selections = mock.Mock()
        app = mock.Mock()
        app.userInterface.activeSelections = selections
        with mock.patch.object(sel.adsk.core.Application, "get", return_value=app), mock.patch.object(sel, "menu_selection", ["a", "b"]):
            sel.restore_menu_selection()
        selections.clear.assert_called_once_with()
        self.assertEqual([call.args[0] for call in selections.add.call_args_list], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
